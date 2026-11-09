"""Rapid UTC (UTCr) policy: keep only values after the latest Circular T date, flagged provisional.

Rapid values are daily and are superseded by the published 5-day UTC values once the next Circular
T appears. So only the days after the latest published date are kept, they are replaced weekly, and
the UI is told they are provisional (`provisional: true` in the snapshot) so it can draw them
differently. In Postgres they are the rows with scale 'utcr'.
"""

from timeglobe_pipeline.bipm_api import Series


def rapid_tail(series: Series, after_mjd: int) -> Series:
    """The part of a rapid series that is strictly later than after_mjd."""
    keep = [i for i, m in enumerate(series.mjd) if m > after_mjd]
    return Series(
        series.name,
        [series.mjd[i] for i in keep],
        [series.value_ns[i] for i in keep],
        [series.unc_ns[i] for i in keep],
    )
