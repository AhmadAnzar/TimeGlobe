"""Replace an API series that fails structural validation with values from Circular T.

A series "needs Circular T" when its dates repeat or run backwards. Its Circular T replacement is
compared with the API series date by date: API values with no published counterpart are excluded
and flagged, never kept, and disagreements are listed rather than resolved.
"""

from dataclasses import dataclass

from timeglobe_pipeline.bipm_api import Series
from timeglobe_pipeline.circular_t import Section1, series_for_lab


@dataclass(frozen=True)
class Comparison:
    both: int
    # (mjd, API values seen for that date, Circular T value)
    value_differences: tuple[tuple[int, tuple[float, ...], float], ...]
    # (mjd, API uncertainties seen, Circular T uncertainty)
    uncertainty_differences: tuple[tuple[int, tuple[float, ...], float | None], ...]
    # (mjd, API values) for dates the API has but Circular T does not: excluded and flagged
    api_only: tuple[tuple[int, tuple[float, ...]], ...]
    circular_t_only: tuple[int, ...]


@dataclass(frozen=True)
class Rebuilt:
    series: Series
    comparison: Comparison


def needs_circular_t(series: Series) -> bool:
    mjd = series.mjd
    return len(set(mjd)) != len(mjd) or any(b < a for a, b in zip(mjd, mjd[1:]))


def compare(api: Series, circular_t: Series) -> Comparison:
    api_values: dict[int, set[float]] = {}
    api_unc: dict[int, set[float]] = {}
    for mjd, value, unc in zip(api.mjd, api.value_ns, api.unc_ns):
        api_values.setdefault(mjd, set()).add(value)
        if unc is not None:
            api_unc.setdefault(mjd, set()).add(unc)
    ct = {m: (v, u) for m, v, u in zip(circular_t.mjd, circular_t.value_ns, circular_t.unc_ns)}

    shared = sorted(set(api_values) & set(ct))
    value_diffs = tuple(
        (m, tuple(sorted(api_values[m])), ct[m][0]) for m in shared if api_values[m] != {ct[m][0]}
    )
    unc_diffs = tuple(
        (m, tuple(sorted(api_unc.get(m, ()))), ct[m][1])
        for m in shared
        if api_unc.get(m, set()) != ({ct[m][1]} if ct[m][1] is not None else set())
    )
    api_only = tuple((m, tuple(sorted(api_values[m]))) for m in sorted(set(api_values) - set(ct)))
    return Comparison(len(shared), value_diffs, unc_diffs, api_only, tuple(sorted(set(ct) - set(api_values))))


def rebuild_from_circular_t(api: Series, sections: list[Section1], code: str) -> Rebuilt:
    series = series_for_lab(sections, code)
    return Rebuilt(series, compare(api, series))
