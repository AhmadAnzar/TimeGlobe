import json
from pathlib import Path

import pytest

from timeglobe_pipeline.bipm_api import parse_series
from timeglobe_pipeline.circular_t import parse_section1
from timeglobe_pipeline.circular_t_index import parse_md5sums
from timeglobe_pipeline.issue_integrity import (
    MAX_LISTED_CHANGES,
    classify,
    diff_issues,
    md5_of,
    needs_download,
    run_detail,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def index():
    return parse_md5sums((FIXTURES / "cirt_MD5SUMS").read_text(encoding="ascii"))


@pytest.fixture(scope="module")
def issue465():
    return (FIXTURES / "cirt.465").read_bytes()


def edited(text: str, lab_prefix: str, old: str, new: str) -> str:
    """The same issue with one token changed on one lab's row."""
    lines = text.split("\r\n")
    i = next(i for i, line in enumerate(lines) if line.startswith(lab_prefix))
    assert old in lines[i]
    lines[i] = lines[i].replace(old, new, 1)
    return "\r\n".join(lines)


# --- the real case: issue 465's file is stable but the index lists another checksum -------------


def test_issue_465_fixture_is_the_served_file_and_the_index_disagrees_with_it(index, issue465):
    # Refetched with the cache bypassed on 9 Nov 2026: byte-identical to this copy, and neither
    # matches the checksum MD5SUMS lists. Issues 453-464 do match (test_circular_t_index.py).
    assert md5_of(issue465) == "a3c76cb35d262c00cc9627673e68c7f5"
    assert index[465] == "83cefa06857c73b1f4468af7091fb00e"


def test_the_465_situation_is_classified_as_an_index_mismatch_not_a_change(index, issue465):
    stored = md5_of(issue465)
    assert needs_download(stored, index[465])
    assert classify(stored, index[465], downloaded=issue465) == "index_mismatch"


def test_issue_465_content_agrees_with_the_api_on_every_value():
    section = parse_section1((FIXTURES / "cirt.465").read_bytes().decode())
    checked = 0
    for code in ("NIST", "APL"):
        (api,) = parse_series((FIXTURES / f"bipm_utc_{code.lower()}.json").read_bytes())
        by_mjd = dict(zip(api.mjd, api.value_ns))
        row = next(r for r in section.labs if r.code == code)
        for mjd, value in zip(section.mjd, row.values_ns):
            assert by_mjd[mjd] == value
            checked += 1
    assert checked == 14


# --- classification ---------------------------------------------------------------------------


def test_matching_checksum_is_ok_and_needs_no_download():
    assert not needs_download("a" * 32, "a" * 32)
    assert classify("a" * 32, "a" * 32, None) == "ok"


def test_an_issue_the_index_no_longer_lists_is_flagged_missing():
    assert needs_download("a" * 32, None)
    assert classify("a" * 32, None, None) == "missing"


def test_a_different_body_is_classified_as_changed(index, issue465):
    stored = md5_of(issue465)
    assert classify(stored, index[465], downloaded=issue465 + b" ") == "changed"


def test_a_mismatch_cannot_be_classified_without_downloading_again():
    with pytest.raises(ValueError):
        classify("a" * 32, "b" * 32, None)


# --- the diff ---------------------------------------------------------------------------------


def test_identical_issues_have_an_empty_diff(issue465):
    diff = diff_issues(issue465.decode(), issue465.decode())
    assert diff.lines_changed == 0 and diff.section1_changes == () and diff.excerpt == ()


def test_a_revised_value_and_uncertainty_are_reported_exactly(issue465):
    old = issue465.decode()
    new = edited(old, "NIST (Boulder)", "     -1.0 ", "     -1.5 ")  # first date, MJD 61279
    new = edited(new, "OP   (Paris)", "   1.3     ", "   1.4     ")  # u of OP
    diff = diff_issues(old, new)
    assert diff.lines_changed == 4  # two lines removed, two added
    changes = {(c.lab, c.mjd, c.field): (c.old, c.new) for c in diff.section1_changes}
    assert changes[("NIST", 61279, "value")] == (-1.0, -1.5)
    assert len(diff.section1_changes) >= 2
    assert any(c.lab == "OP" and c.field in ("uB", "u") for c in diff.section1_changes)
    assert diff.labs_added == () and diff.labs_removed == ()
    assert any(line.startswith("-NIST") for line in diff.excerpt)


def test_a_dropped_lab_row_is_reported(issue465):
    old = issue465.decode()
    lines = [line for line in old.split("\r\n") if not line.startswith("USNO (Washington DC)")]
    diff = diff_issues(old, "\r\n".join(lines))
    assert diff.labs_removed == ("USNO",)


def test_a_body_that_does_not_parse_still_gets_a_line_diff(issue465):
    diff = diff_issues(issue465.decode(), "not a circular t")
    assert diff.parse_error and diff.lines_changed > 0 and diff.section1_changes == ()


# --- what goes into ingest_runs.details -------------------------------------------------------


def test_run_detail_is_json_serialisable_and_caps_the_change_list(issue465):
    old = issue465.decode()
    new = old.replace("0.2   ", "0.3   ")  # touches many uncertainties
    diff = diff_issues(old, new)
    detail = run_detail(465, "changed", "a" * 32, "b" * 32, "c" * 32, diff)
    json.dumps(detail)
    assert detail["kind"] == "changed" and detail["downloaded_md5"] == "c" * 32
    assert detail["value_changes"] == len(diff.section1_changes)
    assert len(detail["changes"]) == min(len(diff.section1_changes), MAX_LISTED_CHANGES)


def test_run_detail_without_a_diff_has_just_the_checksums():
    detail = run_detail(465, "index_mismatch", "a" * 32, "b" * 32, "a" * 32)
    assert detail == {
        "kind": "index_mismatch", "stored_md5": "a" * 32, "listed_md5": "b" * 32,
        "downloaded_md5": "a" * 32,
    }


# --- an examined index_mismatch is not downloaded again until the index entry changes ---------


def test_a_confirmed_mismatch_is_not_downloaded_again_while_the_index_entry_is_unchanged():
    stored, listed = "a" * 32, "b" * 32
    assert needs_download(stored, listed)  # not yet examined
    assert needs_download(stored, listed, confirmed_for=None)
    assert not needs_download(stored, listed, confirmed_for=listed)  # examined: body unchanged


def test_a_changed_index_entry_brings_the_download_back():
    stored = "a" * 32
    assert needs_download(stored, "c" * 32, confirmed_for="b" * 32)


def test_a_missing_entry_and_a_matching_entry_are_unaffected_by_the_confirmation():
    assert needs_download("a" * 32, None, confirmed_for="b" * 32)
    assert not needs_download("a" * 32, "a" * 32, confirmed_for="b" * 32)
