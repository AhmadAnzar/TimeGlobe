"""Daily integrity check of stored Circular T issues against the MD5SUMS index.

Every stored issue keeps the md5 of the body as it was downloaded. Each day the job compares that
with the md5 now listed in MD5SUMS. When they differ it downloads the issue again and classifies
what happened, because a checksum can disagree with a file that never changed:

  ok              stored md5 equals the listed md5; nothing to do
  index_mismatch  the issue was downloaded again and is byte-identical to the stored copy, yet the
                  index lists another checksum (observed for issue 465); flagged, not re-ingested
  changed         the downloaded body differs from the stored copy: re-ingest it and log the diff
  missing         the index no longer lists the issue; flagged

The diff goes into ingest_runs.details so every revision BIPM makes is on record. Pure functions
only: fetching and storing are done by the ingest job.
"""

import difflib
import hashlib
from dataclasses import dataclass

from timeglobe_pipeline.circular_t import ParseError, parse_section1

MAX_LISTED_CHANGES = 200
MAX_EXCERPT_LINES = 20


def md5_of(body: bytes) -> str:
    return hashlib.md5(body).hexdigest()


def needs_download(stored_md5: str, listed_md5: str | None) -> bool:
    """A stored issue is downloaded again only when the index disagrees with it (or lost it)."""
    return listed_md5 is None or stored_md5 != listed_md5


def classify(stored_md5: str, listed_md5: str | None, downloaded: bytes | None) -> str:
    if listed_md5 is None:
        return "missing"
    if stored_md5 == listed_md5:
        return "ok"
    if downloaded is None:
        raise ValueError("a mismatching issue must be downloaded again to be classified")
    return "index_mismatch" if md5_of(downloaded) == stored_md5 else "changed"


@dataclass(frozen=True)
class ValueChange:
    lab: str
    mjd: int | None  # None: a per-lab uncertainty (uA, uB, u), which belongs to the whole issue
    field: str  # "value" | "uA" | "uB" | "u"
    old: float | None
    new: float | None


@dataclass(frozen=True)
class IssueDiff:
    lines_changed: int
    section1_changes: tuple[ValueChange, ...]
    labs_added: tuple[str, ...]
    labs_removed: tuple[str, ...]
    excerpt: tuple[str, ...]
    parse_error: str | None = None


def _line_changes(old: str, new: str) -> tuple[int, tuple[str, ...]]:
    lines = [
        line
        for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]
    return len(lines), tuple(line[:120] for line in lines[:MAX_EXCERPT_LINES])


def diff_issues(old: str, new: str) -> IssueDiff:
    """Line-level diff plus, when both parse, the Section 1 values and uncertainties that changed."""
    count, excerpt = _line_changes(old, new)
    try:
        before, after = parse_section1(old), parse_section1(new)
    except ParseError as exc:
        return IssueDiff(count, (), (), (), excerpt, parse_error=str(exc))
    old_rows = {lab.code: lab for lab in before.labs}
    new_rows = {lab.code: lab for lab in after.labs}
    changes: list[ValueChange] = []
    for code in sorted(old_rows.keys() & new_rows.keys()):
        a, b = old_rows[code], new_rows[code]
        old_values = dict(zip(before.mjd, a.values_ns))
        new_values = dict(zip(after.mjd, b.values_ns))
        for mjd in sorted(old_values.keys() | new_values.keys()):
            if old_values.get(mjd) != new_values.get(mjd):
                changes.append(ValueChange(code, mjd, "value", old_values.get(mjd), new_values.get(mjd)))
        for name, x, y in (("uA", a.u_a, b.u_a), ("uB", a.u_b, b.u_b), ("u", a.u, b.u)):
            if x != y:
                changes.append(ValueChange(code, None, name, x, y))
    return IssueDiff(
        count,
        tuple(changes),
        tuple(sorted(new_rows.keys() - old_rows.keys())),
        tuple(sorted(old_rows.keys() - new_rows.keys())),
        excerpt,
    )


def run_detail(issue: int, kind: str, stored_md5: str, listed_md5: str | None,
               downloaded_md5: str | None, diff: IssueDiff | None = None) -> dict:
    """The JSON-able record for ingest_runs.details["issues"][str(issue)]."""
    detail: dict = {"kind": kind, "stored_md5": stored_md5, "listed_md5": listed_md5,
                    "downloaded_md5": downloaded_md5}
    if diff is not None:
        detail.update(
            lines_changed=diff.lines_changed,
            value_changes=len(diff.section1_changes),
            changes=[
                {"lab": c.lab, "mjd": c.mjd, "field": c.field, "old": c.old, "new": c.new}
                for c in diff.section1_changes[:MAX_LISTED_CHANGES]
            ],
            labs_added=list(diff.labs_added),
            labs_removed=list(diff.labs_removed),
            excerpt=list(diff.excerpt),
        )
        if diff.parse_error:
            detail["parse_error"] = diff.parse_error
    return detail
