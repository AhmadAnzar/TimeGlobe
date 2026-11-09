"""The Circular T issue index: the MD5SUMS file in the published-issues folder.

MD5SUMS lists every issue as `<md5>  cirt.<number>`. It answers "what is the newest issue?" without
scraping a web page or probing for the next number, and gives a checksum to verify each download.
"""

import hashlib
import re

from timeglobe_pipeline.http import PoliteClient

ISSUES_URL = "https://webtai.bipm.org/ftp/pub/tai/Circular-T/cirt/"
MD5SUMS_URL = ISSUES_URL + "MD5SUMS"

_LINE = re.compile(r"^([0-9a-f]{32})\s+cirt\.(\d+)$")


class IndexError_(Exception):
    pass


class ChecksumMismatch(Exception):
    pass


def parse_md5sums(text: str) -> dict[int, str]:
    """{issue number: md5}. A line that is not `<md5>  cirt.<n>` is an error, not skipped."""
    index: dict[int, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _LINE.match(line)
        if not match:
            raise IndexError_(f"unexpected MD5SUMS line: {line!r}")
        number = int(match[2])
        if number in index:
            raise IndexError_(f"issue {number} listed twice")
        index[number] = match[1]
    if not index:
        raise IndexError_("MD5SUMS is empty")
    return index


def latest_issue(index: dict[int, str]) -> int:
    return max(index)


def missing_issues(index: dict[int, str]) -> list[int]:
    return [n for n in range(min(index), max(index) + 1) if n not in index]


def verify_issue(number: int, body: bytes, index: dict[int, str]) -> None:
    if number not in index:
        raise ChecksumMismatch(f"issue {number} is not in MD5SUMS")
    actual = hashlib.md5(body).hexdigest()
    if actual != index[number]:
        raise ChecksumMismatch(f"issue {number}: md5 {actual} does not match listed {index[number]}")


def fetch_index(client: PoliteClient) -> dict[int, str]:
    return parse_md5sums(client.get(MD5SUMS_URL).decode("ascii"))
