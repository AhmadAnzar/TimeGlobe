"""Decide what to publish for one lab's API series: keep it, rebuild it from Circular T, or exclude it.

Failing values are excluded and flagged, never repaired. A series whose dates repeat or run
backwards is rebuilt from the published Circular T issues when there are any (see reconcile);
every other blocking problem excludes the series. Non-blocking problems (a junk uncertainty
label) keep the series and are flagged.
"""

from dataclasses import dataclass

from timeglobe_pipeline.bipm_api import Series
from timeglobe_pipeline.circular_t import Section1
from timeglobe_pipeline.reconcile import needs_circular_t, rebuild_from_circular_t
from timeglobe_pipeline.validate import validate_series


@dataclass(frozen=True)
class Prepared:
    lab: str
    series: Series | None  # None: excluded
    source: str | None  # "api" | "circular_t" | None
    flags: tuple[str, ...]
    circular_t_issues: tuple[int, ...] = ()


def _excluded(lab: str, *reasons: str) -> Prepared:
    return Prepared(lab, None, None, tuple(f"excluded: {r}" for r in reasons))


def prepare_series(
    lab: str, api: Series, sections: list[Section1], known_labs: set[str]
) -> Prepared:
    problems = validate_series(api, lab, known_labs)
    if any(p.kind == "unknown_lab" for p in problems):
        return _excluded(lab, "unknown lab code")

    if needs_circular_t(api):
        rebuilt = rebuild_from_circular_t(api, sections, lab)
        if not rebuilt.series.mjd:
            return _excluded(lab, "repeated or backward dates and no Circular T rows to rebuild from")
        still_bad = [p.detail for p in validate_series(rebuilt.series, lab, known_labs) if p.blocking]
        if still_bad:
            return _excluded(lab, *still_bad)
        issues = tuple(
            section.issue
            for section in sorted(sections, key=lambda s: s.issue)
            if any(
                row.code == lab and any(v is not None for v in row.values_ns)
                for row in section.labs
            )
        )
        c = rebuilt.comparison
        flags = [
            f"rebuilt from Circular T issues {issues[0]}-{issues[-1]} ({len(rebuilt.series.mjd)} values)"
        ]
        if c.api_only:
            flags.append(
                f"{len(c.api_only)} API-only dates not in Circular T excluded "
                f"(MJD {c.api_only[0][0]}-{c.api_only[-1][0]})"
            )
        if c.value_differences:
            flags.append(
                f"{len(c.value_differences)} values differ between the API and Circular T; "
                "Circular T used"
            )
        return Prepared(lab, rebuilt.series, "circular_t", tuple(flags), issues)

    blocking = [p.detail for p in problems if p.blocking]
    if blocking:
        return _excluded(lab, *blocking)
    return Prepared(lab, api, "api", tuple(p.detail for p in problems))
