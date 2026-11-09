from pathlib import Path

import pytest

from timeglobe_pipeline.circular_t import ParseError, parse_section1, series_for_lab

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def section1():
    return parse_section1((FIXTURES / "cirt.465").read_bytes().decode("utf-8"))


@pytest.fixture(scope="module")
def by_code(section1):
    return {lab.code: lab for lab in section1.labs}


def test_issue_and_dates(section1):
    assert section1.issue == 465
    assert section1.mjd == [61279, 61284, 61289, 61294, 61299, 61304, 61309]


def test_every_lab_row_is_parsed_and_section_stops_at_notes(section1, by_code):
    assert len(section1.labs) == 87
    assert len(by_code) == 87
    assert all(len(lab.values_ns) == 7 for lab in section1.labs)
    assert "ZA" in by_code  # last row of the section


def test_values_and_uncertainties(by_code):
    nist = by_code["NIST"]
    assert nist.city == "Boulder"
    assert nist.values_ns == [-1.0, -1.2, -0.4, -0.3, 0.4, 1.0, 0.9]
    assert (nist.u_a, nist.u_b, nist.u) == (0.2, 2.1, 2.1)


def test_missing_values_are_none_not_zero(by_code):
    assert by_code["AZ"].values_ns[4:] == [None, None, None]


def test_nc_uncertainty_is_none(by_code):
    apl = by_code["APL"]
    assert (apl.u_a, apl.u_b, apl.u) == (0.2, None, None)


def test_lab_with_no_data_at_all(by_code):
    nrl = by_code["NRL"]
    assert nrl.values_ns == [None] * 7
    assert nrl.u_a is None


def test_notes_are_captured(by_code):
    assert by_code["HKO"].notes == (1,)
    assert by_code["PL"].notes == (2,)


def test_city_with_punctuation_and_spaces(by_code):
    assert by_code["CH"].city == "Bern-Wabern"
    assert by_code["BSJ"].city == "Kingston"
    assert by_code["USNO"].city == "Washington DC"


def test_rejects_other_text():
    with pytest.raises(ParseError):
        parse_section1("hello\nworld")


def test_series_for_lab_skips_missing_dates_and_carries_uncertainty(section1):
    series = series_for_lab([section1], "AZ")
    assert series.mjd == [61279, 61284, 61289, 61294]  # the three "-" dates are skipped
    assert series.value_ns == [147.1, 157.2, 159.2, 159.0]
    assert series.unc_ns == [7.1] * 4


def test_series_for_lab_with_nc_uncertainty_has_none(section1):
    assert series_for_lab([section1], "APL").unc_ns == [None] * 7


def test_series_for_lab_unknown_lab_is_empty(section1):
    assert series_for_lab([section1], "NOPE").mjd == []


def test_series_for_lab_rejects_the_same_issue_twice(section1):
    with pytest.raises(ParseError, match="overlap"):
        series_for_lab([section1, section1], "NIST")
