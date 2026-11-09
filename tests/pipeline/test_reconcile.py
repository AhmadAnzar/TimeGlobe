from pathlib import Path

import pytest

from timeglobe_pipeline.bipm_api import parse_series
from timeglobe_pipeline.circular_t import parse_section1
from timeglobe_pipeline.reconcile import compare, needs_circular_t, rebuild_from_circular_t

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def api_series(name: str):
    (series,) = parse_series((FIXTURES / name).read_bytes())
    return series


@pytest.fixture(scope="module")
def az():
    sections = [
        parse_section1((FIXTURES / f"cirt.{n}").read_bytes().decode()) for n in range(454, 466)
    ]
    return rebuild_from_circular_t(api_series("bipm_utc_az.json"), sections, "AZ")


def test_only_structurally_broken_series_need_circular_t():
    assert needs_circular_t(api_series("bipm_utc_az.json"))
    for name in ("bipm_utc_nist.json", "bipm_utc_kebs.json", "bipm_utc_apl.json"):
        assert not needs_circular_t(api_series(name)), name


def test_az_rebuilt_series_is_clean(az):
    assert len(az.series.mjd) == 70
    assert not needs_circular_t(az.series)


def test_az_every_published_value_and_uncertainty_matches_the_api(az):
    c = az.comparison
    assert c.both == 70
    assert c.value_differences == ()
    assert c.uncertainty_differences == ()
    assert c.circular_t_only == ()


def test_az_api_only_points_are_flagged_and_not_in_the_rebuilt_series(az):
    flagged = {mjd: values for mjd, values in az.comparison.api_only}
    assert sorted(flagged) == [60919, 60924, 60929, 60934, 60939, 60944]  # Sep 2025
    assert flagged[60919] == (0.0, 213.6)  # a placeholder next to a plausible value
    assert flagged[60924] == (212.2,)
    assert not set(flagged) & set(az.series.mjd)


def test_compare_reports_a_disagreement_instead_of_resolving_it():
    api = api_series("bipm_utc_nist.json")
    ct = api_series("bipm_utc_nist.json")
    ct = type(ct)(ct.name, ct.mjd, [ct.value_ns[0] + 5.0, *ct.value_ns[1:]], ct.unc_ns)
    result = compare(api, ct)
    assert result.value_differences == ((api.mjd[0], (api.value_ns[0],), api.value_ns[0] + 5.0),)
