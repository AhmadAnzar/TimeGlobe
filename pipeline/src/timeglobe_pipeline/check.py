"""Read-only checks after a run.

    python -m timeglobe_pipeline.check db              row counts per table, recent runs (reads the database)
    python -m timeglobe_pipeline.check snapshot DIR    invariants over the snapshot files (no database)

`db` refuses to start unless TIMEGLOBE_ALLOW_DB=1 is set for that run. It runs selects only and
prints counts, never connection details.
"""

import gzip
import json
import os
import sys
from pathlib import Path

from timeglobe_pipeline import config
from timeglobe_pipeline.fetch import REPO_ROOT

TABLES = [
    "labs", "offsets", "clock_counts", "gnss_offsets",
    "circular_t_issues", "ingest_runs", "schema_migrations",
]
FIRST_FRAME_BUDGET = 300 * 1024


def db_report(conn) -> list[str]:
    """Counts only. Table names are the constants above, never user input."""
    out = ["row counts"]
    for table in TABLES:
        out.append(f"  {table:<20}{conn.execute(f'select count(*) from {table}').fetchone()[0]:>10,}")

    out.append("offsets by scale (active / retracted)")
    for scale, active, retracted in conn.execute(
        "select scale, count(*) filter (where retracted_at is null), "
        "count(*) filter (where retracted_at is not null) from offsets group by scale order by scale"
    ):
        out.append(f"  {scale:<20}{active:>10,} / {retracted:,}")
    row = conn.execute(
        "select count(distinct lab), min(mjd), max(mjd) from offsets "
        "where scale='utc' and retracted_at is null"
    ).fetchone()
    out.append(f"  utc labs with data  {row[0]}, mjd {row[1]} to {row[2]}")
    row = conn.execute(
        "select count(*) filter (where circular_t_no is not null), count(distinct lab) "
        "filter (where circular_t_no is not null) from offsets where scale='utc' and retracted_at is null"
    ).fetchone()
    out.append(f"  utc rows taken from Circular T: {row[0]} in {row[1]} lab(s)")

    out.append("labs by status")
    for status, n in conn.execute("select status, count(*) from labs group by status order by status"):
        out.append(f"  {status:<20}{n:>10}")

    row = conn.execute(
        "select count(*), count(*) filter (where md5 = listed_md5), min(issue), max(issue), "
        "count(*) filter (where mismatch_confirmed_for is not null) from circular_t_issues"
    ).fetchone()
    out.append(f"stored issues: {row[0]} (checksum matches the index for {row[1]}; "
               f"index mismatch confirmed for {row[4]}), {row[2]} to {row[3]}")

    row = conn.execute(
        "select count(*), max(month) from clock_counts where month = (select max(month) from clock_counts)"
    ).fetchone()
    out.append(f"clock counts: {row[0]} labs in the latest month ({row[1]})")

    out.append("migrations: " + ", ".join(
        f"{v} {n}" for v, n in conn.execute("select version, name from schema_migrations order by version")
    ))
    out.append("recent runs (newest first)")
    for run in conn.execute(
        "select id, source, status, rows_added, rows_changed, circular_t_no, "
        "coalesce(jsonb_array_length(jsonb_path_query_array(details, '$.failed[*]')), 0) "
        "from ingest_runs order by id desc limit 8"
    ):
        out.append(f"  #{run[0]:<4}{run[1]:<9}{run[2]:<8}added {run[3]:>7,}  changed {run[4]:>5,}  "
                   f"issue {run[5] or '-'}  failed labs {run[6]}")
    return out


def snapshot_report(directory: Path) -> tuple[list[str], bool]:
    """PASS/FAIL lines for the invariants a snapshot must satisfy, and whether all passed."""
    lines: list[str] = []
    ok = True

    def check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        lines.append(f"{'PASS' if passed else 'FAIL'}  {name}" + (f": {detail}" if detail and not passed else ""))

    def load(rel: str):
        return json.loads((directory / rel).read_text(encoding="utf-8"))

    for name in ("meta.json", "labs.json", "gnss.json"):
        check(f"{name} exists", (directory / name).is_file())
    if not ok:
        return lines, False

    meta, labs, gnss = load("meta.json"), load("labs.json"), load("gnss.json")
    lab_files = sorted((directory / "labs").glob("*.json"))
    frame_files = sorted((directory / "frames").glob("*.json"))
    details = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in lab_files}
    lines.append(
        f"INFO  {len(lab_files)} lab files, {len(frame_files)} frame files, {meta['values']:,} values, "
        f"Circular T {meta['circular_t_latest']}, built {meta['generated_at']}"
    )

    check("every lab file is strictly increasing in date and aligned",
          all(len(d["mjd"]) == len(d["v"]) == len(d["u"]) and
              all(b > a for a, b in zip(d["mjd"], d["mjd"][1:])) for d in details.values()))
    check("meta.values equals the values in the lab files",
          meta["values"] == sum(len(d["mjd"]) for d in details.values()),
          f"{meta['values']} vs {sum(len(d['mjd']) for d in details.values())}")
    cells = sum(v is not None for f in frame_files for row in json.loads(f.read_text(encoding='utf-8'))["v"] for v in row)
    check("every value sits in exactly one non-null frame cell", cells == meta["values"], f"{cells} cells vs {meta['values']}")
    check("frame years match meta.years", [int(f.stem) for f in frame_files] == meta["years"])
    check("labs.json has meta.labs labs", len(labs["labs"]) == meta["labs"])
    check("labs with data match the lab files",
          sorted(l["code"] for l in labs["labs"] if l["has_data"]) == sorted(details) and meta["labs_with_data"] == len(details))
    check("a lab's size counts only its own clocks",
          meta["clocks"]["in_labs"] == sum(l["clocks"] for l in labs["labs"])
          and meta["clocks"]["total"] == meta["clocks"]["in_labs"] + sum(meta["clocks"]["unmapped"].values()))
    rapid = {c: d["rapid"] for c, d in details.items() if "rapid" in d}
    check("rapid values are provisional, after the latest Circular T date, and counted in meta",
          len(rapid) == meta["rapid"]["labs"]
          and all(r["provisional"] is True and min(r["mjd"]) > meta["rapid"]["after_mjd"] for r in rapid.values())
          and meta["rapid"]["after_mjd"] == meta["mjd_last"])
    check("gnss has the four systems", sorted(gnss) == ["beidou", "galileo", "glonass", "gps"])
    needed = [directory / "meta.json", directory / "labs.json", frame_files[-1]]
    size = sum(len(gzip.compress(p.read_bytes(), 9, mtime=0)) for p in needed)
    check(f"first-frame payload under 300 KB ({size / 1024:.0f} KB gzip)", size < FIRST_FRAME_BUDGET)
    rebuilt = sorted(c for c, d in details.items() if d["source"] == "circular_t")
    lines.append(f"INFO  labs built from Circular T: {rebuilt or 'none'}; labs with rapid values: {len(rapid)}")
    lines.append(f"INFO  flags: {json.dumps(meta['flags'])[:300] if meta['flags'] else 'none'}")
    return lines, ok


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("db", "snapshot"):
        print(__doc__)
        return 2
    if argv[0] == "snapshot":
        if len(argv) != 2:
            print("usage: check snapshot DIR", file=sys.stderr)
            return 2
        lines, ok = snapshot_report(Path(argv[1]))
        print("\n".join(lines))
        return 0 if ok else 1
    config.require_db_opt_in()
    config.load_env(REPO_ROOT / ".env")
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        print("\n".join(db_report(conn)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
