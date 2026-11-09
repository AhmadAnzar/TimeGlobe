"""BIPM Time Department API v1.0 (https://webtai.bipm.org/api/v1.0/index.html)."""

import json
from dataclasses import dataclass

from timeglobe_pipeline.http import PoliteClient

API_URL = "https://webtai.bipm.org/api/v1.0/get-data.html"


class ApiError(Exception):
    pass


@dataclass(frozen=True)
class Series:
    name: str
    mjd: list[int]
    value_ns: list[float]
    unc_ns: list[float | None]
    # (mjd, raw text) for uncertainty entries that were neither a number nor "-"/null.
    # BIPM sometimes puts labels such as "AZ" or "CirT.453" there; they become None here.
    unc_unparsed: tuple[tuple[int, str], ...] = ()


def _unc(raw: str | None) -> tuple[float | None, bool]:
    """Return (value, parsed_ok). Uncertainties arrive as strings; null (before Dec 2006) and
    "-" (not published, e.g. Circular T's NC) mean none. Other non-numeric text is junk."""
    if raw is None or raw.strip() in ("", "-"):
        return None, True
    try:
        return float(raw), True
    except ValueError:
        return None, False


def _load(body: bytes) -> dict:
    payload = json.loads(body)
    # The lab list ('list' argument) has no status keys; data responses always do.
    if payload.get("success") is False:
        raise ApiError(f"API error {payload.get('errorcode')}: {payload.get('message')}")
    return payload


def parse_labs(body: bytes) -> list[str]:
    return [code.upper() for code in _load(body)["labo"]]


def parse_series(body: bytes) -> list[Series]:
    """Parse a get-data response. The API sends uncertainties as strings, or null when
    unpublished (before MJD 54074 for UTC-UTC(k)), so they are converted here."""
    series = []
    for item in _load(body)["data"]:
        parsed = [_unc(u) for u in item["unc"]]
        unc = [value for value, _ in parsed]
        unparsed = tuple(
            (mjd, raw) for mjd, raw, (_, ok) in zip(item["x"], item["unc"], parsed) if not ok
        )
        if not (len(item["x"]) == len(item["y"]) == len(unc)):
            raise ApiError(f"ragged series {item['name']}")
        series.append(
            Series(item["name"], item["x"], [float(y) for y in item["y"]], unc, unparsed)
        )
    return series


def fetch_labs(client: PoliteClient) -> list[str]:
    return parse_labs(client.get(API_URL, {"list": "", "outfile": "json"}))


def fetch_utc(client: PoliteClient, lab: str, scale: str = "utc") -> Series:
    (series,) = parse_series(
        client.get(API_URL, {"scale": scale, "lab": lab.lower(), "outfile": "json"})
    )
    return series
