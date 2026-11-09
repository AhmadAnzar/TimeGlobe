from pathlib import Path

from timeglobe_pipeline.bipm_api import parse_series
from timeglobe_pipeline.rapid import rapid_tail

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def rapid(name: str):
    (series,) = parse_series((FIXTURES / name).read_bytes())
    return series


def test_only_days_strictly_after_the_cutoff_are_kept():
    tail = rapid_tail(rapid("bipm_utcr_nist.json"), 61309)
    assert (tail.mjd[0], tail.mjd[-1], len(tail.mjd)) == (61310, 61345, 36)
    assert len(tail.mjd) == len(tail.value_ns) == len(tail.unc_ns)


def test_values_line_up_with_their_dates_after_trimming():
    nist = rapid("bipm_utcr_nist.json")
    tail = rapid_tail(nist, 61309)
    by_mjd = dict(zip(nist.mjd, nist.value_ns))
    assert all(by_mjd[m] == v for m, v in zip(tail.mjd, tail.value_ns))


def test_a_cutoff_at_or_after_the_last_day_leaves_nothing():
    nist = rapid("bipm_utcr_nist.json")
    assert rapid_tail(nist, nist.mjd[-1]).mjd == []
    assert rapid_tail(nist, nist.mjd[-1] + 5).mjd == []


def test_a_cutoff_before_the_start_keeps_everything():
    uz = rapid("bipm_utcr_uz.json")
    assert rapid_tail(uz, 0).mjd == uz.mjd
