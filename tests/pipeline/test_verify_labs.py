from pathlib import Path

import pytest

from timeglobe_pipeline.labs import Lab
from timeglobe_pipeline.verify_labs import (
    Hit,
    flags_for,
    haversine_km,
    parse_result,
    query_for,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def lab(**kw) -> Lab:
    base = dict(code="X", name="n", city="Paris", country="France", iso2="FR", lat=48.84, lon=2.34,
                year_start=1970, year_stop=None, status="current", notes="")
    return Lab(**{**base, **kw})


def test_parse_result_reads_a_real_nominatim_response():
    hit = parse_result((FIXTURES / "nominatim_paris.json").read_bytes())
    assert hit is not None
    assert hit.iso2 == "FR"
    assert 48.7 < hit.lat < 49.0 and 2.1 < hit.lon < 2.6
    assert "Paris" in hit.display_name


def test_parse_result_empty_list_is_no_hit():
    assert parse_result(b"[]") is None


def test_haversine_known_distances():
    assert haversine_km(48.85, 2.35, 48.85, 2.35) == 0
    assert haversine_km(48.8566, 2.3522, 51.5074, -0.1278) == pytest.approx(344, abs=3)  # Paris-London


def test_query_for_uses_city_and_country_with_special_cases():
    assert query_for(lab()) == "Paris, France"
    assert query_for(lab(city="Frankfurt/M", country="Germany")) == "Frankfurt am Main, Germany"
    assert query_for(lab(city="Hong Kong", country="China (Hong Kong)")) == "Hong Kong"


def test_flags_far_point_and_country_mismatch_and_no_result():
    hit = Hit(48.85, 2.35, "FR", "Paris")
    assert flags_for(lab(), hit) == []
    assert flags_for(lab(lat=49.5, lon=2.34), hit) == ["72 km off"]
    assert flags_for(lab(iso2="BE"), hit) == ["country BE vs FR"]
    assert flags_for(lab(), None) == ["no result"]


def test_real_laurel_response_reproduces_the_known_ambiguity():
    # "Laurel, United States" resolves to a Kentucky county, ~670 km from Laurel, Maryland.
    hit = parse_result((FIXTURES / "nominatim_laurel.json").read_bytes())
    flags = flags_for(lab(city="Laurel", country="United States", iso2="US", lat=39.10, lon=-76.85), hit)
    assert len(flags) == 1 and flags[0].endswith("km off")


def test_hong_kong_uses_bipms_country_not_openstreetmaps():
    hit = Hit(22.28, 114.16, "CN", "Hong Kong, China")
    hk = lab(city="Hong Kong", country="Hong Kong (China)", iso2="HK", lat=22.30, lon=114.17)
    assert flags_for(hk, hit) == []
    assert flags_for(lab(iso2="FR"), Hit(48.85, 2.35, "CN", "x")) == ["country FR vs CN"]
