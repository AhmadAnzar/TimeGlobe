"""Build the static snapshot from saved inputs: python -m timeglobe_pipeline.build [options]

Reads saved API responses (one UTC-UTC(k) JSON per lab), Circular T issues, the GNSS response, the
clock list page and MD5SUMS, validates every series, and writes the snapshot folder. It makes no
network calls. Options: --series-dir, --rapid-dir, --issues-dir, --gnss, --clocks, --md5sums, --out, --date.
"""

import argparse
import re
import shutil
import sys
from datetime import date
from pathlib import Path

from timeglobe_pipeline import bipm_api, circular_t_index, clock_list
from timeglobe_pipeline.circular_t import parse_section1
from timeglobe_pipeline.fetch import REPO_ROOT
from timeglobe_pipeline.labs import load_labs
from timeglobe_pipeline.prepare import prepare_series
from timeglobe_pipeline.snapshot import SnapshotInput, build_snapshot, initial_payload_gzip, sizes

RAW = REPO_ROOT / "pipeline" / "out" / "raw"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--series-dir", type=Path, default=RAW / "utc")
    ap.add_argument("--rapid-dir", type=Path, default=RAW / "utcr")
    ap.add_argument("--issues-dir", type=Path, default=REPO_ROOT / "tests" / "fixtures")
    ap.add_argument("--gnss", type=Path, default=RAW / "phase2" / "gnss.json")
    ap.add_argument("--clocks", type=Path, default=RAW / "phase2" / "clocklab.html")
    ap.add_argument("--md5sums", type=Path, default=RAW / "phase2" / "MD5SUMS")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "pipeline" / "out" / "snapshot")
    ap.add_argument("--date", default=date.today().isoformat())
    args = ap.parse_args(argv)

    labs = load_labs()
    known = {lab.code for lab in labs}
    sections = [
        parse_section1(p.read_bytes().decode("utf-8"))
        for p in sorted(args.issues_dir.iterdir())
        if re.fullmatch(r"cirt\.\d+", p.name)
    ]

    series, sources, flags = {}, {}, {}
    for path in sorted(args.series_dir.glob("*.json")):
        lab = path.stem
        (api,) = bipm_api.parse_series(path.read_bytes())
        prepared = prepare_series(lab, api, sections, known)
        if prepared.flags:
            flags[lab] = prepared.flags
        if prepared.series is not None:
            series[lab], sources[lab] = prepared.series, prepared.source

    rapid = {}
    if args.rapid_dir.is_dir():
        for path in sorted(args.rapid_dir.glob("*.json")):
            (rapid[path.stem],) = bipm_api.parse_series(path.read_bytes())

    clocks = clock_list.parse_clocks(args.clocks.read_bytes().decode("utf-8"))
    totals = clock_list.clock_totals(clocks, known)
    known_clocks, other_clocks = clock_list.active_counts(clocks, known)
    index = circular_t_index.parse_md5sums(args.md5sums.read_text(encoding="ascii"))
    files = build_snapshot(
        SnapshotInput(
            labs=labs,
            series=series,
            sources=sources,
            gnss=bipm_api.parse_gnss(args.gnss.read_bytes()),
            clocks=known_clocks,
            circular_t_latest=circular_t_index.latest_issue(index),
            generated_at=args.date,
            flags=flags,
            unmapped_clocks=other_clocks,
            rapid=rapid,
        )
    )

    if args.out.exists():
        shutil.rmtree(args.out)
    for rel, body in files.items():
        target = args.out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)

    table = sizes(files)
    total_raw = sum(r for r, _ in table.values())
    total_gz = sum(g for _, g in table.values())
    print(f"{len(series)} labs with data, {sum(len(s.mjd) for s in series.values()):,} values, "
          f"{len(files)} files, {total_raw / 1024:.0f} KB raw / {total_gz / 1024:.0f} KB gzip")
    print(f"clocks ({clock_list.CLOCK_DEFINITION}): {totals.total} in total, {totals.in_labs} in labs, "
          f"unmapped {totals.unmapped}")
    print(f"initial payload (meta + labs + latest year of frames): "
          f"{initial_payload_gzip(files) / 1024:.0f} KB gzip (target: under 300 KB)")
    for rel in ("labs.json", "meta.json", "gnss.json"):
        print(f"  {rel}: {table[rel][0] / 1024:.0f} KB raw / {table[rel][1] / 1024:.0f} KB gzip")
    biggest_frame = max((p for p in table if p.startswith("frames/")), key=lambda p: table[p][1])
    biggest_lab = max((p for p in table if p.startswith("labs/")), key=lambda p: table[p][1])
    print(f"  largest frame {biggest_frame}: {table[biggest_frame][1] / 1024:.0f} KB gzip; "
          f"largest lab {biggest_lab}: {table[biggest_lab][1] / 1024:.0f} KB gzip")
    for lab, f in sorted(flags.items()):
        print(f"  flag {lab}: {'; '.join(f)}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
