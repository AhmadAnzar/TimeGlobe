"""End-to-end ingest jobs against saved real responses: a fake BIPM, an in-memory store.

Nothing here touches a database or the network.
"""

import json
from datetime import date, timedelta
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
                 utc_overrides=None, mjd1_mode="inclusive", md5sums=None, rapid_overrides=None):
        self.md5sums = md5sums  # bytes to serve as MD5SUMS instead of the saved file
        self.rapid_overrides = rapid_overrides or {}  # lab -> rapid response bytes
        # mjd1_mode: how the API treats &mjd1= on rapid requests: "inclusive", "exclusive",
        # "ignored" (sends the whole history), "empty" (arrays present but empty) or "no_data".
        self.mjd1_mode = mjd1_mode
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
            return httpx.Response(200, content=self.md5sums or (FIXTURES / "cirt_MD5SUMS").read_bytes())
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
        if scale == "utcr" and lab in self.rapid_overrides:
            content = self.rapid_overrides[lab]
        elif not path.exists():
            return httpx.Response(200, content=NOT_FOUND)
        else:
            content = path.read_bytes()
        mjd1 = p.get("mjd1")
        if scale == "utcr" and mjd1:
            content = self.range_response(content, int(mjd1))
        return httpx.Response(200, content=content)

    def range_response(self, content: bytes, mjd1: int) -> bytes:
        if self.mjd1_mode == "ignored":
            return content
        if self.mjd1_mode == "no_data":
            return json.dumps({"success": True, "errorcode": 0, "message": "ok", "data": []}).encode()
        doc = json.loads(content)
        item = doc["data"][0]
        keep = [i for i, x in enumerate(item["x"])
                if self.mjd1_mode != "empty" and (x >= mjd1 if self.mjd1_mode == "inclusive" else x > mjd1)]
        for key in ("x", "y", "unc"):
            item[key] = [item[key][i] for i in keep]
        return json.dumps(doc).encode()


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
    assert sum(line.startswith("PASS") for line in lines) == 17  # 5 files + 12 invariants
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


# --- weekly asks only for the tail (mjd1) -----------------------------------------------------


def utcr_requests(bipm: FakeBipm) -> list[str]:
    return [r for r in bipm.requests if "scale=utcr" in r]


def test_weekly_asks_only_for_the_days_after_the_latest_circular_t_date(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    result = ingest.weekly(store, client, TODAY)
    asked = utcr_requests(bipm)
    assert len(asked) == 4 and all("mjd1=61309" in r for r in asked)  # no full-history request
    assert result.details["rapid_points"] == {"returned": 37, "kept": 36}  # the cutoff day comes back too
    assert result.details["mjd1_ignored"] is False
    assert len(store.load_series("utcr")["NIST"]) == 36


def test_weekly_is_correct_when_the_api_treats_mjd1_as_exclusive():
    store, bipm = MemoryStore(), FakeBipm(mjd1_mode="exclusive")
    client = make_client(bipm)
    ingest.daily(store, client, LABS, TODAY)
    result = ingest.weekly(store, client, TODAY)
    assert result.details["rapid_points"] == {"returned": 36, "kept": 36}
    nist = store.load_series("utcr")["NIST"]
    assert (nist[0].mjd, len(nist)) == (61310, 36)  # the first day is not lost


def test_weekly_stays_correct_but_flags_it_when_the_api_ignores_mjd1():
    store, bipm = MemoryStore(), FakeBipm(mjd1_mode="ignored")
    client = make_client(bipm)
    ingest.daily(store, client, LABS, TODAY)
    result = ingest.weekly(store, client, TODAY)
    assert len(store.load_series("utcr")["NIST"]) == 36  # rapid_tail still trims to the tail
    assert result.details["rapid_points"]["returned"] > 4000
    assert result.details["mjd1_ignored"] is True


@pytest.mark.parametrize("mode", ["empty", "no_data"])
def test_an_empty_answer_for_the_range_is_recorded_not_failed(mode):
    store, bipm = MemoryStore(), FakeBipm(mjd1_mode=mode)
    client = make_client(bipm)
    ingest.daily(store, client, LABS, TODAY)
    result = ingest.weekly(store, client, TODAY)
    assert result.status == "ok" and result.details["failed"] == []
    assert "NIST" in result.details["no_rapid"] and result.rows_added == 0
    assert "NIST" not in store.load_series("utcr")


# --- the monthly guard ------------------------------------------------------------------------


def test_the_clock_list_is_not_fetched_again_within_30_days(run):
    store, bipm, client = run
    ingest.monthly(store, client, LABS, TODAY)
    result = ingest.monthly(store, client, LABS, TODAY + timedelta(days=10))
    assert bipm.count("clocklab.html") == 1  # the second run made no request
    assert result.status == "ok" and result.details["skipped"] is True
    assert (result.rows_added, result.rows_changed) == (0, 0)
    assert result.details["fetched_on"] == "2026-11-09" and "fetched at most every 30 days" in result.details["reason"]


def test_a_skipped_run_carries_the_clock_totals_so_the_snapshot_keeps_them(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    first = ingest.monthly(store, client, LABS, TODAY)
    ingest.monthly(store, client, LABS, TODAY + timedelta(days=5))  # skipped
    assert store.latest_details("monthly")["clocks"] == first.details["clocks"]
    meta = json.loads(ingest.snapshot_files(store, LABS, "2026-11-14")["meta.json"])
    assert meta["clocks"]["unmapped"] == {"F": 26}


def test_the_window_is_measured_from_the_real_fetch_not_from_a_skipped_run(run):
    store, bipm, client = run
    ingest.monthly(store, client, LABS, TODAY)
    ingest.monthly(store, client, LABS, TODAY + timedelta(days=10))  # skipped
    ingest.monthly(store, client, LABS, TODAY + timedelta(days=20))  # skipped
    assert bipm.count("clocklab.html") == 1
    result = ingest.monthly(store, client, LABS, TODAY + timedelta(days=31))  # 31 days after the fetch
    assert bipm.count("clocklab.html") == 2 and "skipped" not in result.details
    assert result.details["fetched_on"] == (TODAY + timedelta(days=31)).isoformat()


def test_force_fetches_the_clock_list_inside_the_window(run):
    store, bipm, client = run
    ingest.monthly(store, client, LABS, TODAY)
    result = ingest.monthly(store, client, LABS, TODAY + timedelta(days=1), force=True)
    assert bipm.count("clocklab.html") == 2 and "skipped" not in result.details


def test_a_monthly_run_recorded_before_the_guard_existed_still_counts(run):
    store, bipm, client = run
    old = store.start_run("monthly")  # the form dev run 3 left: "date" but no "fetched_on"
    store.finish_run(old, status="ok", rows_added=98, rows_changed=0, circular_t_no=None,
                     details={"date": "2026-11-09", "clocks": {"total": 683}})
    result = ingest.monthly(store, client, LABS, TODAY + timedelta(days=3))
    assert bipm.count("clocklab.html") == 0 and result.details["skipped"] is True
    assert result.details["clocks"] == {"total": 683}


def test_a_failed_monthly_run_does_not_start_the_window(run):
    store, bipm, client = run
    failed = store.start_run("monthly")
    store.finish_run(failed, status="failed", rows_added=0, rows_changed=0, circular_t_no=None,
                     details={"date": "2026-11-09", "fetched_on": "2026-11-09"}, error="x")
    ingest.monthly(store, client, LABS, TODAY + timedelta(days=1))
    assert bipm.count("clocklab.html") == 1


def test_force_is_only_accepted_for_the_weekly_and_monthly_jobs():
    from timeglobe_pipeline import run as runner

    assert runner.build_parser().parse_args(["monthly", "--force"]).force is True
    assert runner.build_parser().parse_args(["weekly", "--force"]).force is True
    assert runner.build_parser().parse_args(["monthly"]).force is False
    for job in ("daily", "snapshot"):
        with pytest.raises(SystemExit) as stopped:
            runner.main([job, "--force"])
        assert stopped.value.code == 2


def test_the_printed_summary_says_why_a_run_did_nothing_and_warns_about_ignored_mjd1(run):
    from timeglobe_pipeline import run as runner

    store, bipm, client = run
    ingest.monthly(store, client, LABS, TODAY)
    skipped = ingest.monthly(store, client, LABS, TODAY + timedelta(days=2))
    assert "skipped: the clock list was fetched on 2026-11-09" in runner.summary("monthly", skipped)
    assert "--force" in runner.summary("monthly", skipped)

    store2, ignoring = MemoryStore(), FakeBipm(mjd1_mode="ignored")
    client2 = make_client(ignoring)
    ingest.daily(store2, client2, LABS, TODAY)
    weekly = ingest.weekly(store2, client2, TODAY)
    assert "mjd1 ignored" in runner.summary("weekly", weekly)

    store3, honouring = MemoryStore(), FakeBipm()
    client3 = make_client(honouring)
    ingest.daily(store3, client3, LABS, TODAY)
    assert "warning" not in runner.summary("weekly", ingest.weekly(store3, client3, TODAY))


# --- an examined index_mismatch is capped: no daily re-download of issue 465 ------------------


def md5sums_with(issue: int, md5: str) -> bytes:
    lines = (FIXTURES / "cirt_MD5SUMS").read_text().splitlines()
    out = [f"{md5}  cirt.{issue}" if line.endswith(f"cirt.{issue}") else line for line in lines]
    return ("\n".join(out) + "\n").encode()


def test_issue_465_is_examined_once_and_then_not_downloaded_again(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    assert bipm.count("cirt.465") == 1  # the first download, stored as unverified
    second = ingest.daily(store, client, LABS, TODAY)
    assert bipm.count("cirt.465") == 2  # examined: downloaded again, body unchanged
    assert second.details["issues"]["465"]["kind"] == "index_mismatch"
    assert second.details["issues"]["465"]["redownloaded"] is True
    for _ in range(3):
        again = ingest.daily(store, client, LABS, TODAY)
        assert again.details["issues"]["465"]["kind"] == "index_mismatch"  # still flagged every day
        assert again.details["issues"]["465"]["redownloaded"] is False
        assert again.status == "ok" and again.rows_added == 0
    assert bipm.count("cirt.465") == 2  # three more daily runs, no more downloads
    assert store.stored_issues()[465].mismatch_confirmed_for == "83cefa06857c73b1f4468af7091fb00e"


def test_the_download_comes_back_when_the_index_entry_changes(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    ingest.daily(store, client, LABS, TODAY)  # examined
    changed_index = FakeBipm(md5sums=md5sums_with(465, "f" * 32))
    result = ingest.daily(store, make_client(changed_index), LABS, TODAY)
    assert changed_index.count("cirt.465") == 1  # the entry changed, so it is looked at again
    assert result.details["issues"]["465"]["redownloaded"] is True
    again = ingest.daily(store, make_client(changed_index), LABS, TODAY)  # same new entry: settled
    assert changed_index.count("cirt.465") == 1 and again.details["issues"]["465"]["redownloaded"] is False


def test_a_file_that_changes_while_the_index_entry_stays_the_same_is_not_looked_at_again(run):
    # The documented trade-off of the cap: the index entry is what triggers a re-check.
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    ingest.daily(store, client, LABS, TODAY)
    revised = FakeBipm(issue_overrides={465: revised_465()})
    result = ingest.daily(store, make_client(revised), LABS, TODAY)
    assert revised.count("cirt.465") == 0 and result.details["ingested"] is False


def test_a_revision_the_index_now_matches_settles_the_issue(run):
    import hashlib

    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    ingest.daily(store, client, LABS, TODAY)
    body = revised_465()
    settled = FakeBipm(issue_overrides={465: body}, md5sums=md5sums_with(465, hashlib.md5(body).hexdigest()))
    result = ingest.daily(store, make_client(settled), LABS, TODAY)
    assert result.details["issues"]["465"]["kind"] == "changed"  # re-ingested with its diff
    assert store.stored_issues()[465].mismatch_confirmed_for is None
    after = ingest.daily(store, make_client(settled), LABS, TODAY)
    assert "465" not in after.details["issues"] and settled.count("cirt.465") == 1  # ok: nothing to flag


# --- weekly skips labs recorded as having no rapid series, and asks again monthly -------------


def test_labs_with_no_rapid_series_are_recorded_with_the_date_they_were_asked(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    result = ingest.weekly(store, client, TODAY)
    assert result.details["rapid_empty"] == {"APL": "2026-11-09", "AZ": "2026-11-09", "KEBS": "2026-11-09"}
    assert result.details["skipped_no_rapid"] == []


def test_the_next_weekly_run_skips_them(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    ingest.weekly(store, client, TODAY)
    before = len(utcr_requests(bipm))
    result = ingest.weekly(store, client, TODAY + timedelta(days=7))
    new = utcr_requests(bipm)[before:]
    assert len(new) == 1 and "lab=nist" in new[0]  # only the lab that has rapid data
    assert result.details["skipped_no_rapid"] == ["APL", "AZ", "KEBS"]
    assert result.details["no_rapid"] == []  # nothing was found empty this time, they were not asked
    assert result.details["rapid_empty"]["APL"] == "2026-11-09"  # the window runs from the real request
    assert len(store.load_series("utcr")["NIST"]) == 36


def test_after_a_month_they_are_asked_again_and_a_new_rapid_series_is_picked_up(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    ingest.weekly(store, client, TODAY)
    ingest.weekly(store, client, TODAY + timedelta(days=21))  # still inside the window: skipped
    nist_rapid = (FIXTURES / "bipm_utcr_nist.json").read_bytes()
    gaining = FakeBipm(rapid_overrides={"apl": nist_rapid})  # APL gains a rapid series
    later = ingest.weekly(store, make_client(gaining), TODAY + timedelta(days=31))
    assert len(utcr_requests(gaining)) == 4  # all four labs asked again
    assert later.details["skipped_no_rapid"] == []
    assert "APL" not in later.details["rapid_empty"]
    assert len(store.load_series("utcr")["APL"]) == 36  # picked up
    assert later.details["rapid_empty"]["AZ"] == (TODAY + timedelta(days=31)).isoformat()


def test_force_asks_every_lab_again(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    ingest.weekly(store, client, TODAY)
    before = len(utcr_requests(bipm))
    ingest.weekly(store, client, TODAY + timedelta(days=1), force=True)
    assert len(utcr_requests(bipm)) - before == 4


def test_a_series_that_exists_but_has_nothing_new_is_not_recorded_as_having_no_rapid_data():
    store, bipm = MemoryStore(), FakeBipm(mjd1_mode="empty")
    client = make_client(bipm)
    ingest.daily(store, client, LABS, TODAY)
    result = ingest.weekly(store, client, TODAY)
    assert "NIST" in result.details["no_rapid"]  # nothing to keep this week
    assert "NIST" not in result.details["rapid_empty"]  # but it is asked again next week


def test_the_summary_mentions_the_skipped_labs(run):
    from timeglobe_pipeline import run as runner

    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    ingest.weekly(store, client, TODAY)
    result = ingest.weekly(store, client, TODAY + timedelta(days=7))
    assert "3 labs with no rapid series skipped" in runner.summary("weekly", result)


# --- generated_at is the last data-changing run, not today ------------------------------------


def extended_nist_rapid() -> bytes:
    doc = json.loads((FIXTURES / "bipm_utcr_nist.json").read_bytes())
    item = doc["data"][0]
    item["x"].append(item["x"][-1] + 1)  # one more rapid day than the fixture has
    item["y"].append(0.5)
    item["unc"].append(None)
    return json.dumps(doc).encode()


def test_a_run_that_changes_nothing_does_not_count_as_a_data_change(run):
    store, bipm, client = run
    assert ingest.daily(store, client, LABS, TODAY).details["data_changed"] is True
    assert ingest.daily(store, client, LABS, TODAY + timedelta(days=1)).details["data_changed"] is False


def test_an_unchanged_weekly_run_writes_nothing_and_is_not_a_data_change(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    first = ingest.weekly(store, client, TODAY)
    assert first.details["data_changed"] is True and first.rows_added == 36
    again = ingest.weekly(store, client, TODAY + timedelta(days=7))
    assert (again.rows_added, again.details["rapid_changed"], again.details["data_changed"]) == (0, 0, False)
    assert len(store.load_series("utcr")["NIST"]) == 36


def test_a_weekly_run_that_brings_a_new_rapid_day_is_a_data_change(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    ingest.weekly(store, client, TODAY)
    more = FakeBipm(rapid_overrides={"nist": extended_nist_rapid()})
    result = ingest.weekly(store, make_client(more), TODAY + timedelta(days=7))
    assert result.details["data_changed"] is True and result.rows_added == 37
    assert len(store.load_series("utcr")["NIST"]) == 37


def test_the_snapshot_date_is_the_last_data_changing_run_not_today(run):
    store, bipm, client = run
    day = lambda n: TODAY + timedelta(days=n)  # noqa: E731
    ingest.daily(store, client, LABS, day(0))
    assert ingest.snapshot_date(store, day(30)) == "2026-11-09"
    ingest.daily(store, client, LABS, day(1))  # nothing new
    assert ingest.snapshot_date(store, day(1)) == "2026-11-09"
    ingest.weekly(store, client, day(2))  # first rapid tail: a change
    assert ingest.snapshot_date(store, day(2)) == day(2).isoformat()
    ingest.weekly(store, client, day(3))  # identical: not a change
    assert ingest.snapshot_date(store, day(3)) == day(2).isoformat()
    ingest.monthly(store, client, LABS, day(4))  # clock counts: a change
    assert ingest.snapshot_date(store, day(5)) == day(4).isoformat()
    ingest.monthly(store, client, LABS, day(10))  # inside the window: skipped
    assert ingest.snapshot_date(store, day(20)) == day(4).isoformat()


def test_a_day_with_nothing_new_leaves_the_snapshot_byte_identical(run):
    store, bipm, client = run
    ingest.daily(store, client, LABS, TODAY)
    ingest.weekly(store, client, TODAY)
    ingest.monthly(store, client, LABS, TODAY)
    before = ingest.snapshot_files(store, LABS, ingest.snapshot_date(store, TODAY))
    ingest.daily(store, client, LABS, TODAY + timedelta(days=1))
    after = ingest.snapshot_files(store, LABS, ingest.snapshot_date(store, TODAY + timedelta(days=1)))
    assert before == after  # so the workflow commits nothing and no deploy is triggered


def test_an_empty_store_falls_back_to_today():
    assert ingest.snapshot_date(MemoryStore(), TODAY) == "2026-11-09"


def test_the_checks_catch_a_rapid_file_that_disagrees_with_the_lab_files(run, tmp_path):
    directory = written_snapshot(run, tmp_path)
    path = directory / "rapid.json"
    doc = json.loads(path.read_text())
    doc["after_mjd"] = 1
    path.write_text(json.dumps(doc))
    lines, ok = check.snapshot_report(directory)
    assert not ok and any(l.startswith("FAIL  rapid.json holds exactly") for l in lines)


def test_the_checks_catch_a_lab_in_two_clusters(run, tmp_path):
    directory = written_snapshot(run, tmp_path)
    path = directory / "clusters.json"
    doc = json.loads(path.read_text())
    bucket = doc["buckets"][0]
    bucket["clusters"].append(bucket["clusters"][0])  # the same labs twice
    path.write_text(json.dumps(doc))
    lines, ok = check.snapshot_report(directory)
    assert not ok and any(l.startswith("FAIL  clusters.json") for l in lines)
