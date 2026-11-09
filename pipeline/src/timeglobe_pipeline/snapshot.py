"""Static JSON snapshots: the files the globe loads, built from validated data.

Layout (all paths relative to the snapshot folder):
  meta.json            freshness, counts, attribution, flags
  labs.json            every lab (BIPM text verbatim + iso2) and the map sites
  frames/<year>.json   one row per date, one column per lab, null where there is no value
  labs/<code>.json     one lab's full series with uncertainties (loaded when it is picked); a lab
                       with rapid values after the latest Circular T date also has "rapid",
                       always marked provisional so the UI can draw it differently
  gnss.json            the four GNSS offsets from UTC

Values are integers in tenths of a nanosecond (the source resolution is 0.1 ns), so no float noise
reaches the browser. null always means "no data" and is never written as 0. Output is
deterministic: the same input gives the same bytes.
"""

import gzip
import json
from dataclasses import dataclass, field
from datetime import date, timedelta

from timeglobe_pipeline.attribution import ATTRIBUTION
from timeglobe_pipeline.bipm_api import Series
from timeglobe_pipeline.clock_list import CLOCK_DEFINITION
from timeglobe_pipeline.labs import Lab, group_sites
from timeglobe_pipeline.rapid import rapid_tail

EPOCH = date(1858, 11, 17)


@dataclass(frozen=True)
class SnapshotInput:
    labs: list[Lab]
    series: dict[str, Series]  # validated UTC-UTC(k) per lab code
    sources: dict[str, str]  # lab code -> "api" | "circular_t"
    gnss: dict[str, Series]
    clocks: dict[str, int]  # clocks not marked stopped, per lab code
    circular_t_latest: int
    generated_at: str  # ISO date, passed in so builds are reproducible
    rapid: dict[str, Series] = field(default_factory=dict)  # full rapid series; trimmed here
    flags: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unmapped_clocks: dict[str, int] = field(default_factory=dict)


def tenths(value: float) -> int:
    scaled = value * 10
    if abs(scaled - round(scaled)) > 1e-6:
        raise ValueError(f"{value} is not on the 0.1 ns grid")
    return round(scaled)


def year_of(mjd: int) -> int:
    return (EPOCH + timedelta(days=mjd)).year


def _dump(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _packed(series: Series) -> dict:
    return {
        "mjd": series.mjd,
        "v": [tenths(v) for v in series.value_ns],
        "u": [None if u is None else tenths(u) for u in series.unc_ns],
    }


def build_snapshot(data: SnapshotInput) -> dict[str, bytes]:
    labs = sorted(data.labs, key=lambda lab: lab.code)
    codes = [lab.code for lab in labs]
    column = {code: i for i, code in enumerate(codes)}
    sites = sorted(group_sites(labs), key=lambda s: s.codes)
    site_of = {code: i for i, site in enumerate(sites) for code in site.codes}
    files: dict[str, bytes] = {}

    files["labs.json"] = _dump(
        {
            "labs": [
                {
                    "code": lab.code,
                    "name": lab.name,
                    "city": lab.city,
                    "country": lab.country,
                    "iso2": lab.iso2,
                    "lat": lab.lat,
                    "lon": lab.lon,
                    "year_start": lab.year_start,
                    "year_stop": lab.year_stop,
                    "status": lab.status,
                    "clocks": data.clocks.get(lab.code, 0),
                    "site": site_of[lab.code],
                    "has_data": lab.code in data.series,
                }
                for lab in labs
            ],
            "sites": [
                {
                    "id": i,
                    "lat": s.lat,
                    "lon": s.lon,
                    "city": s.city,
                    "country": s.country,
                    "labs": list(s.codes),
                }
                for i, s in enumerate(sites)
            ],
        }
    )

    by_year: dict[int, dict[int, list[int | None]]] = {}
    for code, series in data.series.items():
        for mjd, value in zip(series.mjd, series.value_ns):
            row = by_year.setdefault(year_of(mjd), {}).setdefault(mjd, [None] * len(codes))
            row[column[code]] = tenths(value)
    for year, rows in sorted(by_year.items()):
        dates = sorted(rows)
        files[f"frames/{year}.json"] = _dump(
            {"year": year, "labs": codes, "mjd": dates, "v": [rows[d] for d in dates]}
        )

    all_mjd = [m for s in data.series.values() for m in s.mjd]
    latest_published = max(all_mjd)  # the latest Circular T date
    flags = {code: list(f) for code, f in data.flags.items()}
    rapid_labs = 0
    for code, series in sorted(data.series.items()):
        detail = {"code": code, "source": data.sources.get(code, "api"), **_packed(series)}
        tail = rapid_tail(data.rapid[code], latest_published) if code in data.rapid else None
        if tail is not None and tail.mjd:
            detail["rapid"] = {**_packed(tail), "provisional": True}
            rapid_labs += 1
        files[f"labs/{code}.json"] = _dump(detail)
    for code in sorted(set(data.rapid) - set(data.series)):
        flags.setdefault(code, []).append("rapid values ignored: no published series")

    files["gnss.json"] = _dump({system: _packed(s) for system, s in sorted(data.gnss.items())})

    clocks_in_labs = sum(data.clocks.values())
    files["meta.json"] = _dump(
        {
            "attribution": ATTRIBUTION,
            "circular_t_latest": data.circular_t_latest,
            "generated_at": data.generated_at,
            "mjd_first": min(all_mjd),
            "mjd_last": max(all_mjd),
            "labs": len(labs),
            "labs_with_data": len(data.series),
            "values": sum(len(s.mjd) for s in data.series.values()),
            "years": sorted(by_year),
            "unit": "values are integer tenths of a nanosecond; null means no data",
            "flags": {code: f for code, f in sorted(flags.items()) if f},
            # Computed on every build from the clock list, never a constant. A lab's size uses only
            # clocks filed under its own code; clocks under other codes count in the total only.
            "clocks": {
                "definition": CLOCK_DEFINITION,
                "total": clocks_in_labs + sum(data.unmapped_clocks.values()),
                "in_labs": clocks_in_labs,
                "unmapped": dict(sorted(data.unmapped_clocks.items())),
            },
            "rapid": {"provisional": True, "after_mjd": latest_published, "labs": rapid_labs},
        }
    )
    return files


def sizes(files: dict[str, bytes]) -> dict[str, tuple[int, int]]:
    """{path: (raw bytes, gzip bytes)}: gzip is what a CDN serves."""
    return {path: (len(body), len(gzip.compress(body, 9, mtime=0))) for path, body in files.items()}


def initial_payload_gzip(files: dict[str, bytes]) -> int:
    """Gzip bytes the globe needs for its first frame: meta, labs and the latest year's frames."""
    latest = max(int(p.split("/")[1].removesuffix(".json")) for p in files if p.startswith("frames/"))
    needed = ["meta.json", "labs.json", f"frames/{latest}.json"]
    all_sizes = sizes({p: files[p] for p in needed})
    return sum(gz for _, gz in all_sizes.values())
