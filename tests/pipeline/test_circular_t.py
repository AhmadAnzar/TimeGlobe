from dataclasses import replace
from pathlib import Path

import pytest

from timeglobe_pipeline.circular_t import ParseError, issue_by_mjd, parse_section1, series_for_lab

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


def test_the_same_issue_twice_is_idempotent(section1):
    assert series_for_lab([section1, section1], "NIST") == series_for_lab([section1], "NIST")


def test_conflicting_values_for_one_date_raise(section1):
    nist = next(lab for lab in section1.labs if lab.code == "NIST")
    revised = replace(nist, values_ns=[nist.values_ns[0] + 1.0, *nist.values_ns[1:]])
    other = replace(
        section1,
        issue=section1.issue + 1,
        labs=[revised if lab.code == "NIST" else lab for lab in section1.labs],
    )
    with pytest.raises(ParseError, match="MJD 61279"):
        series_for_lab([section1, other], "NIST")


def issue(n: int):
    return parse_section1((FIXTURES / f"cirt.{n}").read_bytes().decode("utf-8"))


def test_issue_454_has_eight_dates_and_multi_note_markers():
    section = issue(454)
    assert len(section.mjd) == 8 and section.mjd[0] == 60944
    az = next(lab for lab in section.labs if lab.code == "AZ")
    assert az.values_ns == [None, 239.9, 255.7, 248.1, 262.3, 271.7, 287.6, 298.9]
    assert az.notes == (1, 2)
    assert (az.u_a, az.u_b, az.u) == (0.2, 7.1, 7.1)


def test_issue_453_has_no_az_row():
    section = issue(453)
    assert "AZ" not in {lab.code for lab in section.labs}
    assert series_for_lab([section], "AZ").mjd == []


def test_consecutive_issues_share_a_boundary_date_with_the_same_value():
    a, b = issue(455), issue(456)
    az_a = next(lab for lab in a.labs if lab.code == "AZ")
    az_b = next(lab for lab in b.labs if lab.code == "AZ")
    assert a.mjd[-1] == b.mjd[0] == 61009
    assert az_a.values_ns[-1] == az_b.values_ns[0] == 390.1
    series = series_for_lab([a, b], "AZ")
    assert series.mjd.count(61009) == 1 and len(series.mjd) == 13


def test_az_from_issues_454_to_465():
    series = series_for_lab([issue(n) for n in range(454, 466)], "AZ")
    assert len(series.mjd) == 70
    assert (series.mjd[0], series.mjd[-1]) == (60949, 61294)
    assert all(b > a for a, b in zip(series.mjd, series.mjd[1:]))
    assert series.value_ns[0] == 239.9 and series.value_ns[-1] == 159.0
    assert 0.0 not in series.value_ns
    assert set(series.unc_ns) == {7.0, 7.1}


def test_issue_by_mjd_names_the_issue_each_kept_date_comes_from():
    sections = [issue(n) for n in range(454, 466)]
    by_mjd = issue_by_mjd(sections, "AZ")
    assert sorted(by_mjd) == series_for_lab(sections, "AZ").mjd  # exactly the dates that are kept
    assert by_mjd[60949] == 454 and by_mjd[61294] == 465
    assert by_mjd[61009] == 455  # shared with 456: the earlier issue wins
    assert issue_by_mjd(sections, "NOPE") == {}
