from pathlib import Path

import pytest

from timeglobe_pipeline.bipm_api import parse_labs as parse_api_labs
from timeglobe_pipeline.circular_t import parse_section1
from timeglobe_pipeline.labs import group_sites, load_labs
from timeglobe_pipeline.time_database import parse_labs as parse_time_database

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def labs():
    return load_labs()


def test_every_api_lab_has_exactly_one_row(labs):
    api = parse_api_labs((FIXTURES / "bipm_labs.json").read_bytes())
    assert sorted(lab.code for lab in labs) == sorted(api)


def test_current_labs_are_exactly_those_in_circular_t_with_its_cities(labs):
    section1 = parse_section1((FIXTURES / "cirt.465").read_bytes().decode("utf-8"))
    current = {lab.code: lab for lab in labs if lab.status == "current"}
    assert set(current) == {row.code for row in section1.labs}
    for row in section1.labs:
        assert current[row.code].city == row.city


def test_status_agrees_with_time_database_years(labs):
    db = {
        lab.code: lab
        for lab in parse_time_database((FIXTURES / "bipm_showlab.html").read_bytes().decode())
    }
    for lab in labs:
        assert (lab.year_start, lab.year_stop) == (db[lab.code].year_start, db[lab.code].year_stop)
        assert lab.name == db[lab.code].name
        assert (lab.status == "former") == (lab.year_stop is not None), lab.code


def test_all_labs_have_valid_coordinates_and_iso2(labs):
    for lab in labs:
        assert -90 <= lab.lat <= 90, lab.code
        assert -180 <= lab.lon <= 180, lab.code
        assert len(lab.iso2) == 2 and lab.iso2.isupper(), lab.code
        assert lab.country, lab.code


def test_labs_in_the_same_city_share_one_point(labs):
    points: dict[tuple[str, str], set[tuple[float, float]]] = {}
    for lab in labs:
        points.setdefault((lab.city, lab.country), set()).add((lab.lat, lab.lon))
    assert {key: p for key, p in points.items() if len(p) > 1} == {}


def test_sites_list_every_lab_at_a_shared_point(labs):
    sites = {site.codes: site for site in group_sites(labs)}
    assert ("BIRM", "NIM") in sites  # Beijing
    assert ("HKO", "SCL") in sites
    assert ("NRL", "USNO") in sites
    assert ("ORB", "SMD") in sites
    assert ("IGNA", "INTI", "ONBA") in sites
    assert sites[("IGNA", "INTI", "ONBA")].count == 3
    assert sum(site.count for site in sites.values()) == len(labs)
    assert len({code for site in sites.values() for code in site.codes}) == len(labs)


def test_hong_kong_labs_carry_bipms_country_wording(labs):
    db = {
        lab.code: lab
        for lab in parse_time_database((FIXTURES / "bipm_showlab.html").read_bytes().decode())
    }
    hk = [lab for lab in labs if lab.iso2 == "HK"]
    assert {lab.code for lab in hk} == {"HKO", "SCL"}
    assert all(lab.country == db[lab.code].country == "Hong Kong (China)" for lab in hk)
