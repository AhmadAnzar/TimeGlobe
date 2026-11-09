"""Uncertainty bands for the drift chart.

A band exists only where BIPM published an uncertainty. Before that (UTC-UTC(k) uncertainties
start at MJD 54074, 2006-12-05) and wherever the uncertainty is "-"/junk, there is no band at all,
never a zero-width one, so a chart cannot suggest "exactly known".
"""

from dataclasses import dataclass

from timeglobe_pipeline.bipm_api import Series


@dataclass(frozen=True)
class Band:
    mjd: int
    low_ns: float
    high_ns: float


def uncertainty_bands(series: Series) -> list[Band]:
    return [
        Band(mjd, value - unc, value + unc)
        for mjd, value, unc in zip(series.mjd, series.value_ns, series.unc_ns)
        if unc is not None and unc > 0
    ]
