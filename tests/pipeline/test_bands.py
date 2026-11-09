from pathlib import Path

import pytest

from timeglobe_pipeline.bands import uncertainty_bands
from timeglobe_pipeline.bipm_api import Series, parse_series

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FIRST_PUBLISHED_UNCERTAINTY_MJD = 54074  # 2006-12-05


def load(name: str) -> Series:
    (series,) = parse_series((FIXTURES / name).read_bytes())
    return series


def test_no_band_before_uncertainties_were_published():
    series = load("bipm_utc_nist.json")
    bands = uncertainty_bands(series)
    assert bands[0].mjd == FIRST_PUBLISHED_UNCERTAINTY_MJD
    assert all(b.mjd >= FIRST_PUBLISHED_UNCERTAINTY_MJD for b in bands)
    before = [m for m in series.mjd if m < FIRST_PUBLISHED_UNCERTAINTY_MJD]
    assert before and not {b.mjd for b in bands} & set(before)


def test_bands_are_never_zero_width():
    for name in ("bipm_utc_nist.json", "bipm_utc_apl.json", "bipm_utc_az.json", "bipm_utc_kebs.json"):
        assert all(b.high_ns > b.low_ns for b in uncertainty_bands(load(name))), name


def test_band_is_value_plus_minus_uncertainty():
    series = load("bipm_utc_nist.json")
    band = uncertainty_bands(series)[-1]
    assert band.mjd == series.mjd[-1]
    assert band.low_ns == pytest.approx(series.value_ns[-1] - 2.1)
    assert band.high_ns == pytest.approx(series.value_ns[-1] + 2.1)


def test_dash_and_junk_uncertainties_give_no_band():
    apl = load("bipm_utc_apl.json")  # "-" from 2024 on
    assert apl.mjd[-1] not in {b.mjd for b in uncertainty_bands(apl)}
    az = load("bipm_utc_az.json")  # "AZ" / "CirT.453" labels
    flagged = {mjd for mjd, _ in az.unc_unparsed}
    assert flagged and not flagged & {b.mjd for b in uncertainty_bands(az)}


def test_zero_uncertainty_is_not_drawn_as_a_band():
    series = Series("X", [1, 2], [1.0, 2.0], [0.0, 1.5])
    assert [b.mjd for b in uncertainty_bands(series)] == [2]
