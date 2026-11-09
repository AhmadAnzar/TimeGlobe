"""Parser for Circular T Section 1: UTC-UTC(k) per laboratory, with uncertainties.

Layout (checked against issue 465): a header with one MJD per column, then one fixed-text
row per lab: `CODE (City)  v1 .. vN  uA uB u [(note)]`. `-` means no value; `NC` means the
type-B uncertainty is not computed. Section 1 ends at the notes block.
"""

import re
from dataclasses import dataclass

from timeglobe_pipeline.bipm_api import Series

_ROW = re.compile(r"^(?P<code>[A-Z0-9]+)\s+\((?P<city>[^)]*)\)\s*(?P<rest>.*)$")
_NOTE = re.compile(r"^\((\d+(?:,\d+)*)\)$")


class ParseError(Exception):
    pass


@dataclass(frozen=True)
class LabRow:
    code: str
    city: str
    values_ns: list[float | None]
    u_a: float | None
    u_b: float | None
    u: float | None
    notes: tuple[int, ...]


@dataclass(frozen=True)
class Section1:
    issue: int
    mjd: list[int]
    labs: list[LabRow]


def _num(token: str) -> float | None:
    return None if token in ("-", "NC") else float(token)


def parse_section1(text: str) -> Section1:
    lines = text.splitlines()
    first = lines[0].split()
    if first[:2] != ["CIRCULAR", "T"]:
        raise ParseError("not a Circular T issue")
    issue = int(first[2])

    start = next(
        (i for i, line in enumerate(lines) if line.startswith("1 - Difference between UTC")), None
    )
    if start is None:
        raise ParseError("section 1 not found")
    mjd_line = next(
        (line for line in lines[start:] if line.strip().startswith("MJD")), None
    )
    if mjd_line is None:
        raise ParseError("MJD header not found")
    mjd = [int(t) for t in mjd_line.split()[1:] if t.isdigit()]

    labs = []
    for line in lines[start:]:
        if line.startswith("- Notes on section 1") or re.match(r"^2 - ", line):
            break
        match = _ROW.match(line.strip())
        if not match:
            continue
        tokens = match["rest"].split()
        notes = tuple(int(n) for t in tokens if (m := _NOTE.match(t)) for n in m[1].split(","))
        tokens = [t for t in tokens if not _NOTE.match(t)]
        if len(tokens) not in (len(mjd), len(mjd) + 3):
            raise ParseError(f"{match['code']}: unexpected column count {len(tokens)}")
        values = [_num(t) for t in tokens[: len(mjd)]]
        u_a, u_b, u = (_num(t) for t in tokens[len(mjd) :]) if len(tokens) > len(mjd) else (None,) * 3
        labs.append(LabRow(match["code"], match["city"].strip(), values, u_a, u_b, u, notes))
    if not labs:
        raise ParseError("no laboratory rows found")
    return Section1(issue, mjd, labs)


def series_for_lab(sections: list[Section1], code: str) -> Series:
    """Build one lab's UTC-UTC(k) series from several issues' Section 1.

    Dates with no value ("-") are skipped, never turned into zero. Each date carries the issue's
    total uncertainty u for that lab (None when it is not computed).

    Consecutive issues share their boundary date (the last column of one issue is the first of
    the next). If both give the same value the date is kept once, with the earlier issue's row,
    which is where it was first published. Two issues giving different values for one date is a
    revision the caller has to decide on, so it raises instead of picking one.
    """
    by_mjd: dict[int, tuple[float, float | None]] = {}
    for section in sorted(sections, key=lambda sec: sec.issue):
        row = next((lab for lab in section.labs if lab.code == code), None)
        if row is None:
            continue
        for date, value in zip(section.mjd, row.values_ns):
            if value is None:
                continue
            if date in by_mjd:
                if by_mjd[date][0] != value:
                    raise ParseError(
                        f"{code}: issue {section.issue} gives {value} for MJD {date}, "
                        f"earlier issue gave {by_mjd[date][0]}"
                    )
                continue
            by_mjd[date] = (value, row.u)
    mjd = sorted(by_mjd)
    return Series(f"UTC-UTC({code})", mjd, [by_mjd[m][0] for m in mjd], [by_mjd[m][1] for m in mjd])


def issue_by_mjd(sections: list[Section1], code: str) -> dict[int, int]:
    """For each date `series_for_lab` keeps, the issue it comes from (the earlier issue wins on
    a shared boundary date). The writer stores it as offsets.circular_t_no."""
    out: dict[int, int] = {}
    for section in sorted(sections, key=lambda sec: sec.issue):
        row = next((lab for lab in section.labs if lab.code == code), None)
        if row is None:
            continue
        for date, value in zip(section.mjd, row.values_ns):
            if value is not None and date not in out:
                out[date] = section.issue
    return out
