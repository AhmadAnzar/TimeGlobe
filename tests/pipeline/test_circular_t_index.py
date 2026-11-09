from pathlib import Path

import pytest

from timeglobe_pipeline.circular_t_index import (
    ChecksumMismatch,
    IndexError_,
    latest_issue,
    missing_issues,
    parse_md5sums,
    verify_issue,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def index():
    return parse_md5sums((FIXTURES / "cirt_MD5SUMS").read_text(encoding="ascii"))


def test_real_md5sums_lists_every_issue_from_100_to_465(index):
    assert (min(index), max(index), len(index)) == (100, 465, 366)
    assert latest_issue(index) == 465
    assert missing_issues(index) == []


@pytest.mark.parametrize("number", range(453, 465))
def test_saved_issues_match_their_listed_checksum(index, number):
    verify_issue(number, (FIXTURES / f"cirt.{number}").read_bytes(), index)


def test_a_changed_byte_is_detected(index):
    body = bytearray((FIXTURES / "cirt.454").read_bytes())
    body[100] ^= 1
    with pytest.raises(ChecksumMismatch, match="454"):
        verify_issue(454, bytes(body), index)


def test_issue_not_in_the_index_is_rejected(index):
    with pytest.raises(ChecksumMismatch, match="not in MD5SUMS"):
        verify_issue(466, b"anything", index)


def test_malformed_and_duplicate_lines_are_errors_not_skipped():
    with pytest.raises(IndexError_, match="unexpected"):
        parse_md5sums("not a checksum line")
    good = "a" * 32 + "  cirt.1"
    with pytest.raises(IndexError_, match="twice"):
        parse_md5sums(good + "\n" + good)
    with pytest.raises(IndexError_, match="empty"):
        parse_md5sums("\n")


def test_gaps_are_reported():
    text = f"{'a' * 32}  cirt.1\n{'b' * 32}  cirt.3\n"
    assert missing_issues(parse_md5sums(text)) == [2]
