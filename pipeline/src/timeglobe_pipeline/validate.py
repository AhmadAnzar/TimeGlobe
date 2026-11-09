"""Validation for a parsed UTC-UTC(k) series (no duplicate dates, values within sane bounds).

Returns problems and never repairs anything: what to do with a bad series is a maintainer
decision, and silently dropping or deduplicating would hide a data problem from the run log.

A problem is *blocking* when the series cannot be trusted as published (repeated or backward
dates, zeros on such dates, dates off the expected grid, absurd values, an unknown lab). It is
non-blocking when only a label is wrong (a junk uncertainty entry becomes "no uncertainty").
A plain 0.0 is a real value and common, so it is only suspicious on repeated or backward dates.
"""

from dataclasses import dataclass

from timeglobe_pipeline.bipm_api import Series

MAX_ABS_NS = 1_000_000.0  # the largest real value seen so far is ~95,000 ns


@dataclass(frozen=True)
class Problem:
    kind: str
    detail: str
    blocking: bool


def _repeated_or_backward_positions(mjd: list[int]) -> set[int]:
    """Indexes whose date was already seen or is not later than the previous date."""
    seen: set[int] = set()
    flagged: set[int] = set()
    for i, date in enumerate(mjd):
        if date in seen or (i and date < mjd[i - 1]):
            flagged.add(i)
        seen.add(date)
    return flagged


def validate_series(
    series: Series,
    lab: str | None = None,
    known_labs: set[str] | None = None,
    grid_origin_mjd: int = 50814,
    step: int = 5,
) -> list[Problem]:
    problems: list[Problem] = []
    mjd = series.mjd
    if lab is not None and known_labs is not None and lab not in known_labs:
        problems.append(Problem("unknown_lab", f"unknown lab code {lab}", True))
    duplicates = len(mjd) - len(set(mjd))
    if duplicates:
        problems.append(Problem("duplicate_dates", f"{duplicates} duplicate dates", True))
    backwards = sum(b < a for a, b in zip(mjd, mjd[1:]))
    if backwards:
        problems.append(Problem("backward_dates", f"dates go backwards {backwards} times", True))
    bad_positions = _repeated_or_backward_positions(mjd)
    zeros = sum(series.value_ns[i] == 0.0 for i in bad_positions)
    if zeros:
        problems.append(
            Problem("zeros_on_repeated_dates", f"{zeros} zero values on repeated or backward dates", True)
        )
    off_grid = sum((m - grid_origin_mjd) % step != 0 for m in mjd)
    if off_grid:
        problems.append(Problem("off_grid", f"{off_grid} dates off the {step}-day grid", True))
    huge = sum(abs(v) > MAX_ABS_NS for v in series.value_ns)
    if huge:
        problems.append(Problem("huge_values", f"{huge} values beyond +-{MAX_ABS_NS:g} ns", True))
    if series.unc_unparsed:
        labels = sorted({raw for _, raw in series.unc_unparsed})
        problems.append(
            Problem("junk_uncertainty", f"{len(series.unc_unparsed)} junk uncertainty entries {labels}", False)
        )
    return problems


def check_series(series: Series, grid_origin_mjd: int = 50814, step: int = 5) -> list[str]:
    """Problem descriptions only (no lab check): kept for quick use in scripts and tests."""
    return [p.detail for p in validate_series(series, None, None, grid_origin_mjd, step)]
