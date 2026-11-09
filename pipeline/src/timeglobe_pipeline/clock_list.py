"""Parser for the Time Database clock list (https://webtai.bipm.org/database/clocklab.html).

The page lists every clock that took part in UTC, one row each: laboratory, BIPM clock code, maker
and type, comment. Clocks that stopped have "(stopped)" after the code. A row's lab can be a code
that is not one of the laboratories ("F": French clocks at other sites, named in the comment).
"""

import html
import re
from collections import Counter
from dataclasses import dataclass

_TABLE = re.compile(r"<table[^>]*>(.*?)</table>", re.S | re.I)
_ROW = re.compile(r"<tr>\s*((?:<td[^>]*>.*?</td>\s*){4})</tr>", re.S | re.I)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")
HEADING = "ALL participating clocks"
CLOCK_DEFINITION = "clocks not marked stopped on the Time Database clock list"


class ParseError(Exception):
    pass


@dataclass(frozen=True)
class Clock:
    lab: str
    code: str
    maker: str
    comment: str
    stopped: bool


def _text(cell: str) -> str:
    return " ".join(html.unescape(_TAGS.sub("", cell)).split())


def parse_clocks(page: str) -> list[Clock]:
    start = page.find(HEADING)
    if start < 0:
        raise ParseError("clock table not found")
    table = _TABLE.search(page, start)
    if not table:
        raise ParseError("clock table not found")
    clocks = []
    for row in _ROW.findall(table.group(1)):
        lab, code, maker, comment = (_text(c) for c in _CELL.findall(row))
        stopped = code.endswith("(stopped)")
        clocks.append(Clock(lab, code.removesuffix("(stopped)").strip(), maker, comment, stopped))
    if not clocks:
        raise ParseError("no clock rows found")
    return clocks


def active_counts(clocks: list[Clock], known_labs: set[str]) -> tuple[dict[str, int], dict[str, int]]:
    """Clocks not marked stopped, per lab: (counts for known labs, counts for other lab codes)."""
    counts = Counter(c.lab for c in clocks if not c.stopped)
    known = {lab: n for lab, n in counts.items() if lab in known_labs}
    other = {lab: n for lab, n in counts.items() if lab not in known_labs}
    return known, other


@dataclass(frozen=True)
class ClockTotals:
    total: int  # every clock not marked stopped, including those filed under non-lab codes
    in_labs: int  # the part that belongs to laboratories: what a lab's own size is made of
    unmapped: dict[str, int]  # non-lab codes (e.g. "F"): in the total, never in a lab's size
    stopped: int


def clock_totals(clocks: list[Clock], known_labs: set[str]) -> ClockTotals:
    """Computed from the page on every run; there is no stored or hardcoded total."""
    per_lab, unmapped = active_counts(clocks, known_labs)
    return ClockTotals(
        total=sum(per_lab.values()) + sum(unmapped.values()),
        in_labs=sum(per_lab.values()),
        unmapped=unmapped,
        stopped=sum(c.stopped for c in clocks),
    )
