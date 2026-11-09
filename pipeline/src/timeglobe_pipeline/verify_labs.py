"""Check pipeline/data/labs.csv against Nominatim: python -m timeglobe_pipeline.verify_labs

Reports every lab whose point is more than 50 km from where Nominatim puts "city, country", or
whose country code differs. It never edits labs.csv; a maintainer reviews the report.
Policy: at most 1 request/s, our User-Agent, responses cached on disk (see PoliteClient).
"""

import csv
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

from timeglobe_pipeline.fetch import REPO_ROOT
from timeglobe_pipeline.http import FetchError, PoliteClient
from timeglobe_pipeline.labs import Lab, load_labs

SEARCH_URL = "https://nominatim.openstreetmap.org/search"
MAX_KM = 50.0

# BIPM lists Hong Kong as its own country; OpenStreetMap files it under CN. BIPM wins.
ACCEPTED_OSM_COUNTRY = {"HK": {"CN"}}

# Circular T city spellings Nominatim cannot resolve as written.
QUERY_CITY = {"Frankfurt/M": "Frankfurt am Main"}


@dataclass(frozen=True)
class Hit:
    lat: float
    lon: float
    iso2: str
    display_name: str


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def query_for(lab: Lab) -> str:
    city = QUERY_CITY.get(lab.city, lab.city)
    # "China (Hong Kong)" is not a place name Nominatim understands.
    return city if "(" in lab.country else f"{city}, {lab.country}"


def parse_result(body: bytes) -> Hit | None:
    results = json.loads(body)
    if not results:
        return None
    top = results[0]
    return Hit(
        float(top["lat"]),
        float(top["lon"]),
        top.get("address", {}).get("country_code", "").upper(),
        top["display_name"],
    )


def search(client: PoliteClient, query: str) -> Hit | None:
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": "1",
        "addressdetails": "1",
        "accept-language": "en",
    }
    return parse_result(client.get(SEARCH_URL, params))


def flags_for(lab: Lab, hit: Hit | None) -> list[str]:
    if hit is None:
        return ["no result"]
    flags = []
    km = haversine_km(lab.lat, lab.lon, hit.lat, hit.lon)
    if km > MAX_KM:
        flags.append(f"{km:.0f} km off")
    if hit.iso2 != lab.iso2 and hit.iso2 not in ACCEPTED_OSM_COUNTRY.get(lab.iso2, set()):
        flags.append(f"country {lab.iso2} vs {hit.iso2 or '?'}")
    return flags


def main() -> int:
    from timeglobe_pipeline import config

    config.load_env(REPO_ROOT / ".env")
    labs = load_labs()
    out = REPO_ROOT / "pipeline" / "out" / "geocode_report.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    hits: dict[str, Hit | None] = {}
    flagged = 0
    with PoliteClient(
        config.user_agent(),
        config.ALLOWED_PREFIXES,
        forbidden_prefixes=config.FORBIDDEN_PREFIXES,
        cache_dir=REPO_ROOT / "pipeline" / ".cache",
        min_interval=1.0,
    ) as client, out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(
            ["code", "query", "csv_lat", "csv_lon", "osm_lat", "osm_lon", "km", "csv_iso2", "osm_iso2", "flags", "osm_name"]
        )
        for lab in labs:
            query = query_for(lab)
            if query not in hits:
                try:
                    hits[query] = search(client, query)
                except FetchError as exc:
                    print(f"{lab.code}: request failed: {exc}", file=sys.stderr)
                    hits[query] = None
            hit = hits[query]
            flags = flags_for(lab, hit)
            km = f"{haversine_km(lab.lat, lab.lon, hit.lat, hit.lon):.1f}" if hit else ""
            writer.writerow(
                [lab.code, query, lab.lat, lab.lon, hit.lat if hit else "", hit.lon if hit else "",
                 km, lab.iso2, hit.iso2 if hit else "", "; ".join(flags), hit.display_name if hit else ""]
            )
            if flags:
                flagged += 1
                print(f"{lab.code:5} {lab.city}, {lab.country}: {'; '.join(flags)}")
    print(f"{flagged} of {len(labs)} labs flagged; full report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
