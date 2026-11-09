"""Validation for a parsed UTC-UTC(k) series (no duplicate dates, values within sane bounds).

Returns human-readable problems and never repairs anything: what to do with a bad series is a
maintainer decision, and silently dropping or deduplicating would hide a data problem from the run log.
"""

from timeglobe_pipeline.bipm_api import Series

MAX_ABS_NS = 1_000_000.0  # the largest real value seen so far is ~95,000 ns


def check_series(series: Series, grid_origin_mjd: int = 50814, step: int = 5) -> list[str]:
    problems = []
    mjd = series.mjd
    duplicates = len(mjd) - len(set(mjd))
    if duplicates:
        problems.append(f"{duplicates} duplicate dates")
    backwards = sum(b < a for a, b in zip(mjd, mjd[1:]))
    if backwards:
        problems.append(f"dates go backwards {backwards} times")
    off_grid = sum((m - grid_origin_mjd) % step != 0 for m in mjd)
    if off_grid:
        problems.append(f"{off_grid} dates off the {step}-day grid")
    huge = sum(abs(v) > MAX_ABS_NS for v in series.value_ns)
    if huge:
        problems.append(f"{huge} values beyond +-{MAX_ABS_NS:g} ns")
    if series.unc_unparsed:
        labels = sorted({raw for _, raw in series.unc_unparsed})
        problems.append(f"{len(series.unc_unparsed)} junk uncertainty entries {labels}")
    return problems
