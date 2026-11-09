"""Parser for the BIPM Time Database laboratory table (https://webtai.bipm.org/database/showlab.html).

One page lists every laboratory that ever took part, with its city, country, and the years it
started and stopped. The page's "2-characters" BIPM code is internal and is not an ISO country code.
"""

import html
import re
from dataclasses import dataclass

_ROW = re.compile(r"<TR(?:\s[^>]*)?>(.*?)</TR>", re.S | re.I)
_CELL = re.compile(r"<TD[^>]*>(.*?)</TD>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")


class ParseError(Exception):
    pass


@dataclass(frozen=True)
class LabInfo:
    code: str
    name: str
    city: str
    country: str
    year_start: int | None
    year_stop: int | None  # None while the lab is still participating


def _text(cell: str) -> str:
    return " ".join(html.unescape(_TAGS.sub("", cell)).split())


def _year(text: str) -> int | None:
    return int(text) if text.isdigit() else None


def parse_labs(page: str) -> list[LabInfo]:
    start = page.find("Acronyms and locations")
    if start < 0:
        raise ParseError("laboratory table not found")
    labs = []
    for row in _ROW.findall(page, start):
        cells = [_text(c) for c in _CELL.findall(row)]
        # Data rows have 10 cells; the two header rows have fewer.
        if len(cells) != 10:
            continue
        code, name, city, country, _mra, _prev, start_year, stop_year, _c2, _num = cells
        labs.append(LabInfo(code, name, city, country, _year(start_year), _year(stop_year)))
    if not labs:
        raise ParseError("no laboratory rows found")
    return labs
