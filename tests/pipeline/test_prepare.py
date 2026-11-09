from pathlib import Path

import pytest

from timeglobe_pipeline.bipm_api import parse_series
from timeglobe_pipeline.circular_t import parse_section1
from timeglobe_pipeline.prepare import prepare_series

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
KNOWN = {"AZ", "NIST", "APL", "KEBS", "MIKE"}


def api(name: str):
    (series,) = parse_series((FIXTURES / name).read_bytes())
    return series


@pytest.fixture(scope="module")
def sections():
    return [
        parse_section1((FIXTURES / f"cirt.{n}").read_bytes().decode()) for n in range(453, 466)
    ]


def test_clean_series_is_kept_as_published(sections):
    prepared = prepare_series("NIST", api("bipm_utc_nist.json"), sections, KNOWN)
    assert prepared.source == "api" and prepared.flags == ()
    assert len(prepared.series.mjd) == 2100


def test_az_is_rebuilt_from_circular_t_and_flagged(sections):
    prepared = prepare_series("AZ", api("bipm_utc_az.json"), sections, KNOWN)
    assert prepared.source == "circular_t"
    assert len(prepared.series.mjd) == 70
    assert prepared.circular_t_issues == tuple(range(454, 466))
    assert prepared.flags == (
        "rebuilt from Circular T issues 454-465 (70 values)",
        "6 API-only dates not in Circular T excluded (MJD 60919-60944)",
    )


def test_junk_uncertainty_label_keeps_the_series_and_flags_it(sections):
    # AZ's labels are non-blocking on their own; use a clean-dated series with one junk entry.
    series = api("bipm_utc_nist.json")
    junk = type(series)(series.name, series.mjd, series.value_ns, series.unc_ns, ((54074, "main"),))
    prepared = prepare_series("NIST", junk, sections, KNOWN)
    assert prepared.series is junk
    assert prepared.flags == ("1 junk uncertainty entries ['main']",)


def test_unknown_lab_is_excluded_and_never_rebuilt(sections):
    prepared = prepare_series("XX", api("bipm_utc_az.json"), sections, KNOWN)
    assert prepared.series is None
    assert prepared.flags == ("excluded: unknown lab code",)


def test_broken_series_with_no_circular_t_rows_is_excluded_not_repaired():
    prepared = prepare_series("AZ", api("bipm_utc_az.json"), [], KNOWN)
    assert prepared.series is None and prepared.source is None
    assert "no Circular T rows" in prepared.flags[0]


def test_other_blocking_problems_exclude_the_series(sections):
    series = api("bipm_utc_nist.json")
    off_grid = type(series)(series.name, [m + 1 for m in series.mjd], series.value_ns, series.unc_ns)
    prepared = prepare_series("NIST", off_grid, sections, KNOWN)
    assert prepared.series is None
    assert prepared.flags == ("excluded: 2100 dates off the 5-day grid",)
