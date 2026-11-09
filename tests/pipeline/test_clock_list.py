from pathlib import Path

import pytest

from timeglobe_pipeline.clock_list import (
    CLOCK_DEFINITION,
    ParseError,
    active_counts,
    clock_totals,
    parse_clocks,
)
from timeglobe_pipeline.labs import load_labs

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def clocks():
    return parse_clocks((FIXTURES / "bipm_clocklab.html").read_bytes().decode("utf-8"))


def test_every_row_is_parsed_and_the_sitemap_is_not(clocks):
    assert len(clocks) == 973
    assert sum(c.stopped for c in clocks) == 290
    assert all(c.lab != "Home" for c in clocks)


def test_stopped_marker_is_split_from_the_code(clocks):
    stopped = next(c for c in clocks if c.lab == "APL" and c.stopped)
    assert stopped.code == "1350904"
    first = clocks[0]
    assert (first.lab, first.code, first.stopped) == ("AGGO", "1350768", False)
    assert "HIGH PERFORMANCE TUBE" in first.maker


def test_active_counts_per_lab_and_unmapped_codes(clocks):
    known = {lab.code for lab in load_labs()}
    counts, other = active_counts(clocks, known)
    assert counts["USNO"] == 63 and counts["NICT"] == 52
    assert sum(counts.values()) == 657
    assert other == {"F": 26}  # French clocks at other sites, not one of the 98 labs


def test_labs_with_no_active_clock_are_absent_from_the_counts(clocks):
    known = {lab.code for lab in load_labs()}
    counts, _ = active_counts(clocks, known)
    assert sorted(known - set(counts)) == [
        "AOS", "CNES", "EE", "INCP", "KEBS", "LDS", "LV", "TUG",
    ]


def test_page_without_the_table_is_rejected():
    with pytest.raises(ParseError):
        parse_clocks("<html></html>")


def test_the_f_clocks_counted_are_exactly_those_not_marked_stopped(clocks):
    f_rows = [c for c in clocks if c.lab == "F"]
    assert len(f_rows) == 42
    assert sum(not c.stopped for c in f_rows) == 26 and sum(c.stopped for c in f_rows) == 16
    assert all(c.code.isdigit() for c in f_rows)  # the "(stopped)" marker is split off the code


def test_totals_count_f_in_the_global_total_but_not_in_any_labs_size(clocks):
    known = {lab.code for lab in load_labs()}
    totals = clock_totals(clocks, known)
    per_lab, _ = active_counts(clocks, known)
    assert totals.unmapped == {"F": 26}
    assert totals.in_labs == sum(per_lab.values())
    assert totals.total == totals.in_labs + 26
    assert totals.stopped == 290
    assert "F" not in per_lab


def test_the_total_follows_the_page_so_nothing_is_stored():
    page = (
        "<h3>ALL participating clocks to UTC :</h3><TABLE border=1>"
        "<tr><td>AAA </td><td>1 </td><td>m</td><td> </td></tr>"
        "<tr><td>AAA </td><td >2 (stopped)</td><td>m</td><td> </td></tr>"
        "<tr><td>F </td><td>3 </td><td>m</td><td> at X</td></tr></TABLE>"
    )
    totals = clock_totals(parse_clocks(page), {"AAA"})
    assert (totals.total, totals.in_labs, totals.stopped, totals.unmapped) == (2, 1, 1, {"F": 1})
    assert CLOCK_DEFINITION == "clocks not marked stopped on the Time Database clock list"
