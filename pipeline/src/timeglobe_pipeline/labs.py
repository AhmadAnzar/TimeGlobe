"""The hand-maintained lab table (pipeline/data/labs.csv) and the map points built from it.

Labs in the same city are one Site: the globe draws a single point with a count badge, and the
lab panel lists every lab at that point. The table keeps shared-city labs on identical
coordinates, which a test enforces, so grouping is an exact match on (lat, lon).
"""

import csv
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "labs.csv"


@dataclass(frozen=True)
class Lab:
    code: str
    name: str
    city: str
    country: str
    iso2: str
    lat: float
    lon: float
    year_start: int | None
    year_stop: int | None
    status: str  # current | former | not_in_issue
    notes: str


@dataclass(frozen=True)
class Site:
    lat: float
    lon: float
    city: str
    country: str
    codes: tuple[str, ...]

    @property
    def count(self) -> int:
        return len(self.codes)


def load_labs(path: Path = DEFAULT_PATH) -> list[Lab]:
    with path.open(encoding="utf-8", newline="") as f:
        return [
            Lab(
                code=r["code"],
                name=r["name"],
                city=r["city"],
                country=r["country"],
                iso2=r["iso2"],
                lat=float(r["lat"]),
                lon=float(r["lon"]),
                year_start=int(r["year_start"]) if r["year_start"] else None,
                year_stop=int(r["year_stop"]) if r["year_stop"] else None,
                status=r["status"],
                notes=r["notes"],
            )
            for r in csv.DictReader(f)
        ]


def group_sites(labs: list[Lab]) -> list[Site]:
    by_point: dict[tuple[float, float], list[Lab]] = {}
    for lab in labs:
        by_point.setdefault((lab.lat, lab.lon), []).append(lab)
    return [
        Site(lat, lon, members[0].city, members[0].country, tuple(sorted(m.code for m in members)))
        for (lat, lon), members in by_point.items()
    ]
