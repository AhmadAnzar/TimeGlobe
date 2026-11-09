from pathlib import Path

import pytest

from timeglobe_pipeline.bipm_api import Series, parse_series
from timeglobe_pipeline.validate import check_series

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


def test_duplicates_are_reported_not_removed():
    series = Series("X", [10, 15, 15], [1.0, 2.0, 2.0], [None, None, None])
    assert check_series(series, grid_origin_mjd=10) == ["1 duplicate dates"]
    assert series.mjd == [10, 15, 15]


def test_off_grid_and_huge_values():
    series = Series("X", [10, 16], [1.0, 2e6], [None, None])
    problems = check_series(series, grid_origin_mjd=10)
    assert "1 dates off the 5-day grid" in problems
    assert any("beyond" in p for p in problems)
