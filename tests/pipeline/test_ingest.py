"""End-to-end ingest jobs against saved real responses: a fake BIPM, an in-memory store.

Nothing here touches a database or the network.
"""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from timeglobe_pipeline import check, config, ingest
from timeglobe_pipeline.http import PoliteClient
from timeglobe_pipeline.labs import load_labs
from timeglobe_pipeline.store import MemoryStore

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LABS = load_labs()
ISSUES = "https://webtai.bipm.org/ftp/pub/tai/Circular-T/cirt/"
API = "https://webtai.bipm.org/api/v1.0/get-data.html"
NOT_FOUND = json.dumps({"success": False, "errorcode": 2, "message": "not found"}).encode()
TODAY = date(2026, 11, 9)


class FakeBipm:
    """Serves the saved responses and records every request."""

    def __init__(self, labs=("nist", "apl", "kebs", "az"), issue_overrides=None, broken=(),
                 utc_overrides=None):
        self.labs = list(labs)
        self.utc_overrides = utc_overrides or {}
        self.issue_overrides = issue_overrides or {}
        self.broken = set(broken)
        self.requests: list[str] = []

    def count(self, needle: str) -> int:
        return sum(needle in r for r in self.requests)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if url == ISSUES + "MD5SUMS":
            return httpx.Response(200, content=(FIXTURES / "cirt_MD5SUMS").read_bytes())
        if url.startswith(ISSUES + "cirt."):
            number = int(url.rsplit(".", 1)[1])
            if number in self.issue_overrides:
                return httpx.Response(200, content=self.issue_overrides[number])
            path = FIXTURES / f"cirt.{number}"
            return httpx.Response(200 if path.exists() else 404, content=path.read_bytes() if path.exists() else b"")
        if url.startswith("https://webtai.bipm.org/database/clocklab.html"):
            return httpx.Response(200, content=(FIXTURES / "bipm_clocklab.html").read_bytes())
        p = request.url.params
        if "list" in p:
            return httpx.Response(200, content=json.dumps({"labo": self.labs}).encode())
        scale, lab = p.get("scale"), p.get("lab")
        if scale == "gnss":
            return httpx.Response(200, content=(FIXTURES / "bipm_gnss.json").read_bytes())
        if lab in self.broken:
            return httpx.Response(500)
        if scale == "utc" and lab in self.utc_overrides:
            return httpx.Response(200, content=self.utc_overrides[lab])
        name = {"utc": f"bipm_utc_{lab}.json", "utcr": f"bipm_utcr_{lab}.json"}[scale]
        path = FIXTURES / name
        return httpx.Response(200, content=path.read_bytes() if path.exists() else NOT_FOUND)


def make_client(bipm: FakeBipm) -> PoliteClient:
    return PoliteClient(
        "test", config.ALLOWED_PREFIXES, forbidden_prefixes=config.FORBIDDEN_PREFIXES,
        transport=httpx.MockTransport(bipm), min_interval=0, max_retries=1, sleep=lambda s: None,
    )


@pytest.fixture
def run():
    store, bipm = MemoryStore(), FakeBipm()
    return store, bipm, make_client(bipm)


def revised_465(old="159.2", new="    -"):
    """Issue 465 with one AZ value replaced (by default blanked to '-'), keeping column widths."""
    lines = (FIXTURES / "cirt.465").read_bytes().decode().split("\r\n")
    i = next(i for i, line in enumerate(lines) if line.startswith("AZ   (Baku)"))
    lines[i] = lines[i].replace(old, new, 1)
    return "\r\n".join(lines).encode()


# --- daily ------------------------------------------------------------------------------------


def test_first_daily_run_ingests_drift_gnss_issues_and_flags(run):
    store, bipm, client = run
    result = ingest.daily(store, client, LABS, TODAY)
    assert result.status == "ok" and result.details["circular_t_latest"] == 465
    series = store.load_series("utc")
    assert sorted(series) == ["APL", "AZ", "KEBS", "NIST"]
    assert len(series["NIST"]) == 2100 and len(series["AZ"]) == 70
    assert set(store.load_gnss()) == {"gps", "glonass", "galileo", "beidou"}
    assert store.last_ingested_issue() == 465
    assert store.runs[0]["status"] == "ok" and store.runs[0]["circular_t_no"] == 465
    stored_rows = sum(len(t) for t in store.offsets.values()) + sum(len(t) for t in store.gnss.values())
    assert result.rows_added == stored_rows  # data rows only
    assert result.details["labs"] == {"added": len(LABS), "changed": 0}  # reference data, kept apart


def test_az_is_rebuilt_from_stored_issues_with_the_issue_recorded_per_date(run):
    store, bipm, client = run
    result = ingest.daily(store, client, LABS, TODAY)
    assert sorted(store.stored_issues()) == list(range(453, 466))  # 453 is where the window stops
    az = store.load_series("utc")["AZ"]
    assert az[0].mjd == 60949 and az[0].circular_t_no == 454
    assert next(r for r in az if r.mjd == 61009).circular_t_no == 455  # shared date: earlier issue
    assert all(r.circular_t_no is not None for r in az)
    assert all(r.circular_t_no is None for r in store.load_series("utc")["NIST"])
    assert result.details["flags"]["AZ"][0] == "rebuilt from Circular T issues 454-465 (70 values)"


def test_issue_465_is_flagged_unverified_and_never_blocks(run):
    store, bipm, client = run
    result = ingest.daily(store, client, LABS, TODAY)
    assert result.status == "ok"
    assert result.details["issues"]["465"]["kind"] == "unverified"


def test_a_second_daily_run_with_nothing_new_writes_nothing_and_keeps_the_flags(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    before = len(bipm.requests)
    result = ingest.daily(store, client, LABS, TODAY)
    new_requests = bipm.requests[before:]
    assert result.details["ingested"] is False and (result.rows_added, result.rows_changed) == (0, 0)
    assert not any("scale=utc" in r or "list" in r for r in new_requests)  # no API series refetched
    assert result.details["issues"]["465"]["kind"] == "index_mismatch"  # flagged again, not re-ingested
    assert result.details["flags"]["AZ"]  # carried forward for the snapshot
    assert store.last_ingested_issue() == 465


def test_a_revised_issue_is_reingested_and_its_diff_is_logged(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    original = (FIXTURES / "cirt.465").read_bytes().decode()
    lines = original.split("\r\n")
    i = next(i for i, line in enumerate(lines) if line.startswith("AZ   (Baku)"))
    lines[i] = lines[i].replace("157.2", "158.2", 1)  # MJD 61284, not the shared boundary date
    revised = FakeBipm(issue_overrides={465: "\r\n".join(lines).encode()})
    result = ingest.daily(store, make_client(revised), LABS, TODAY)
    detail = result.details["issues"]["465"]
    assert detail["kind"] == "changed" and detail["value_changes"] == 1
    assert detail["changes"] == [{"lab": "AZ", "mjd": 61284, "field": "value", "old": 157.2, "new": 158.2}]
    assert result.details["ingested"] is True and result.rows_changed == 1
    az = {r.mjd: r.value_ns for r in store.load_series("utc")["AZ"]}
    assert az[61284] == 158.2
    # the next day the file is stable again: only the index disagrees, and nothing is re-ingested
    again = ingest.daily(store, make_client(revised), LABS, TODAY)
    assert again.details["issues"]["465"]["kind"] == "index_mismatch" and again.rows_changed == 0


def test_a_lab_that_cannot_be_fetched_fails_the_run_after_everything_else_is_written():
    store, bipm = MemoryStore(), FakeBipm(broken=["nist"])
    with pytest.raises(ingest.IngestError, match="NIST"):
        ingest.daily(store, make_client(bipm), LABS, TODAY)
    assert store.runs[-1]["status"] == "failed" and "NIST" in store.runs[-1]["error"]
    assert "APL" in store.load_series("utc") and "NIST" not in store.load_series("utc")
    assert store.last_ingested_issue() is None  # a failed run does not advance; the next one retries


def test_a_lab_with_no_data_yet_is_recorded_but_does_not_fail_the_run():
    store, bipm = MemoryStore(), FakeBipm(labs=("nist", "ee"))
    result = ingest.daily(store, make_client(bipm), LABS, TODAY)
    assert result.status == "ok" and result.details["no_data"] == ["EE"]


def test_a_current_lab_that_vanishes_from_the_api_fails_the_run():
    store, bipm = MemoryStore(), FakeBipm(labs=("nist", "usno"))  # USNO is current, no fixture
    with pytest.raises(ingest.IngestError, match="USNO"):
        ingest.daily(store, make_client(bipm), LABS, TODAY)


# --- weekly -----------------------------------------------------------------------------------


def test_weekly_keeps_only_the_provisional_tail_after_the_latest_circular_t_date(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    result = ingest.weekly(store, client, TODAY)
    assert result.details["after_mjd"] == 61309
    nist = store.load_series("utcr")["NIST"]
    assert (nist[0].mjd, nist[-1].mjd, len(nist)) == (61310, 61345, 36)
    assert result.details["no_rapid"] == ["APL", "AZ", "KEBS"]  # no rapid data for them
    assert result.rows_added == 36


def test_running_weekly_again_replaces_rather_than_duplicates(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    ingest.weekly(store, client, TODAY)
    ingest.weekly(store, client, TODAY)
    assert len(store.load_series("utcr")["NIST"]) == 36


def test_weekly_before_any_daily_run_is_an_error(run):
    store, bipm, client = run
    with pytest.raises(ingest.IngestError, match="daily job first"):
        ingest.weekly(store, client, TODAY)
    assert store.runs[-1]["status"] == "failed"


# --- monthly ----------------------------------------------------------------------------------


def test_monthly_records_counts_and_the_totals_computed_from_the_page(run):
    store, bipm, client = run
    result = ingest.monthly(store, client, LABS, TODAY)
    counts = store.load_clock_counts()
    assert list(store.clock_counts) == [date(2026, 11, 1)]
    assert counts["USNO"] == 63 and counts["AOS"] == 0 and len(counts) == len(LABS)
    clocks = result.details["clocks"]
    assert clocks["in_labs"] == sum(counts.values())
    assert clocks["total"] == clocks["in_labs"] + sum(clocks["unmapped"].values())
    assert clocks["unmapped"] == {"F": 26} and "F" not in counts  # never in a lab's size


# --- snapshot from the store ------------------------------------------------------------------


def test_the_snapshot_is_built_from_the_store(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    ingest.weekly(store, client, TODAY)
    ingest.monthly(store, client, LABS, TODAY)
    files = ingest.snapshot_files(store, LABS, "2026-11-09")
    meta = json.loads(files["meta.json"])
    assert meta["circular_t_latest"] == 465 and meta["labs_with_data"] == 4
    assert meta["flags"]["AZ"][0].startswith("rebuilt from Circular T issues 454-465")
    assert meta["rapid"] == {"provisional": True, "after_mjd": 61309, "labs": 1}
    assert meta["clocks"]["unmapped"] == {"F": 26}
    assert json.loads(files["labs/AZ.json"])["source"] == "circular_t"
    assert json.loads(files["labs/NIST.json"])["rapid"]["provisional"] is True


def test_a_snapshot_with_no_data_is_an_error():
    with pytest.raises(ingest.IngestError, match="no data"):
        ingest.snapshot_files(MemoryStore(), LABS, "2026-11-09")


# --- retraction -------------------------------------------------------------------------------


def test_a_first_ingest_retracts_nothing(run):
    store, bipm, client = run
    result = ingest.daily(store, client, LABS, TODAY)
    assert result.details["retracted"] == {} and store.load_retracted("utc") == {}


def test_a_value_a_revised_issue_no_longer_contains_is_retracted_not_deleted(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    revised = FakeBipm(issue_overrides={465: revised_465()})  # MJD 61289 becomes "-"
    result = ingest.daily(store, make_client(revised), LABS, TODAY)
    assert result.details["retracted"]["AZ"] == {
        "count": 1, "rows": [{"mjd": 61289, "value_ns": 159.2, "circular_t_no": 465}],
    }
    issue = result.details["issues"]["465"]
    assert issue["kind"] == "changed" and issue["value_changes"] == 1 and issue["retracted_rows"] == 1
    assert result.rows_changed == 1  # the retraction is a change to an existing row
    assert 61289 not in {r.mjd for r in store.load_series("utc")["AZ"]}
    assert [r.mjd for r in store.load_retracted("utc")["AZ"]] == [61289]  # still on record


def test_retracted_rows_are_left_out_of_the_snapshot(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    ingest.daily(store, make_client(FakeBipm(issue_overrides={465: revised_465()})), LABS, TODAY)
    files = ingest.snapshot_files(store, LABS, "2026-11-09")
    assert 61289 not in json.loads(files["labs/AZ.json"])["mjd"]
    assert json.loads(files["meta.json"])["values"] == 2100 + 1840 + 263 + 69


def test_a_later_revision_that_brings_the_value_back_restores_the_row(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    ingest.daily(store, make_client(FakeBipm(issue_overrides={465: revised_465()})), LABS, TODAY)
    result = ingest.daily(store, client, LABS, TODAY)  # the original file is served again
    assert result.details["issues"]["465"]["kind"] == "changed"
    assert result.rows_changed == 1 and result.details["retracted"] == {}
    assert 61289 in {r.mjd for r in store.load_series("utc")["AZ"]}
    assert store.load_retracted("utc") == {}


def test_a_truncated_api_response_cannot_retract_a_labs_history(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    raw = json.loads((FIXTURES / "bipm_utc_nist.json").read_bytes())
    for key in ("x", "y", "unc"):
        raw["data"][0][key] = raw["data"][0][key][:100]
    broken = FakeBipm(issue_overrides={465: revised_465()}, utc_overrides={"nist": json.dumps(raw).encode()})
    with pytest.raises(ingest.IngestError, match="NIST"):
        ingest.daily(store, make_client(broken), LABS, TODAY)
    assert len(store.load_series("utc")["NIST"]) == 2100  # nothing was hidden
    assert "NIST" not in store.load_retracted("utc")
    assert "retraction limit" in store.runs[-1]["error"] and store.runs[-1]["status"] == "failed"


# --- the snapshot checks (the ones the maintainer runs on the real output) --------------------


def written_snapshot(run, tmp_path):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    ingest.weekly(store, client, TODAY)
    ingest.monthly(store, client, LABS, TODAY)
    for rel, body in ingest.snapshot_files(store, LABS, "2026-11-09").items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(body)
    return tmp_path


def test_a_snapshot_built_from_the_store_passes_every_check(run, tmp_path):
    lines, ok = check.snapshot_report(written_snapshot(run, tmp_path))
    assert ok, " | ".join(lines)
    assert sum(line.startswith("PASS") for line in lines) == 13  # 3 files + 10 invariants
    assert not any(line.startswith("FAIL") for line in lines)
    assert any("labs built from Circular T: ['AZ']" in line for line in lines)


def test_the_checks_catch_a_value_missing_from_the_frames(run, tmp_path):
    directory = written_snapshot(run, tmp_path)
    frame = directory / "frames" / "2026.json"
    doc = json.loads(frame.read_text())
    doc["v"][0] = [None] * len(doc["v"][0])  # blank a whole row of the frame
    frame.write_text(json.dumps(doc))
    lines, ok = check.snapshot_report(directory)
    assert not ok and any(l.startswith("FAIL  every value sits in exactly one") for l in lines)


def test_the_checks_catch_a_lab_file_out_of_order(run, tmp_path):
    directory = written_snapshot(run, tmp_path)
    path = directory / "labs" / "NIST.json"
    doc = json.loads(path.read_text())
    doc["mjd"][1], doc["mjd"][2] = doc["mjd"][2], doc["mjd"][1]
    path.write_text(json.dumps(doc))
    lines, ok = check.snapshot_report(directory)
    assert not ok and any(l.startswith("FAIL  every lab file is strictly increasing") for l in lines)


def test_the_checks_catch_rapid_values_that_are_not_marked_provisional(run, tmp_path):
    directory = written_snapshot(run, tmp_path)
    path = directory / "labs" / "NIST.json"
    doc = json.loads(path.read_text())
    doc["rapid"]["provisional"] = False
    path.write_text(json.dumps(doc))
    assert not check.snapshot_report(directory)[1]


def test_the_snapshot_command_needs_no_database_and_the_db_command_needs_the_opt_in(run, tmp_path, monkeypatch, capsys):
    assert check.main(["snapshot", str(written_snapshot(run, tmp_path))]) == 0
    assert "PASS" in capsys.readouterr().out
    monkeypatch.delenv("TIMEGLOBE_ALLOW_DB", raising=False)
    with pytest.raises(SystemExit, match="refusing to connect"):
        check.main(["db"])
