from pathlib import Path

import pytest

from timeglobe_pipeline.bipm_api import Series, parse_series
from timeglobe_pipeline.validate import check_series, validate_series

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load(name: str) -> Series:
    (series,) = parse_series((FIXTURES / name).read_bytes())
    return series


@pytest.mark.parametrize("name", ["bipm_utc_nist.json", "bipm_utc_kebs.json", "bipm_utc_apl.json"])
def test_clean_series_have_no_problems(name):
    assert check_series(load(name)) == []


def test_az_real_response_is_flagged_for_repeated_dates_and_junk_labels():
    problems = check_series(load("bipm_utc_az.json"))
    assert "136 duplicate dates" in problems
    assert any(p.startswith("dates go backwards") for p in problems)
    assert any("junk uncertainty entries" in p for p in problems)


def test_az_zeros_on_repeated_dates_are_flagged_as_their_own_problem():
    kinds = {p.kind: p for p in validate_series(load("bipm_utc_az.json"))}
    assert kinds["zeros_on_repeated_dates"].blocking
    assert kinds["duplicate_dates"].blocking and kinds["backward_dates"].blocking
    assert not kinds["junk_uncertainty"].blocking  # a bad label only loses the uncertainty


def test_plain_zero_values_are_genuine_and_not_flagged():
    # USNO, NIST and 59 other labs have real 0.0 values; none of that is a problem by itself.
    series = load("bipm_utc_nist.json")
    assert 0.0 in series.value_ns
    assert validate_series(series, "NIST", {"NIST"}) == []


def test_unknown_lab_code_is_blocking():
    problems = validate_series(load("bipm_utc_nist.json"), "XX", {"NIST"})
    assert [(p.kind, p.blocking) for p in problems] == [("unknown_lab", True)]


def test_daily_series_validate_against_a_one_day_step():
    (utcr,) = parse_series((FIXTURES / "bipm_utcr_nist.json").read_bytes())
    assert validate_series(utcr, "NIST", {"NIST"}, grid_origin_mjd=utcr.mjd[0], step=1) == []
    assert any(p.kind == "off_grid" for p in validate_series(utcr, "NIST", {"NIST"}))


def test_duplicates_are_reported_not_removed():
    series = Series("X", [10, 15, 15], [1.0, 2.0, 2.0], [None, None, None])
    assert check_series(series, grid_origin_mjd=10) == ["1 duplicate dates"]
    assert series.mjd == [10, 15, 15]


def test_off_grid_and_huge_values():
    series = Series("X", [10, 16], [1.0, 2e6], [None, None])
    problems = check_series(series, grid_origin_mjd=10)
    assert "1 dates off the 5-day grid" in problems
    assert any("beyond" in p for p in problems)
