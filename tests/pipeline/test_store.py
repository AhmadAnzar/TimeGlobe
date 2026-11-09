"""Contract tests: MemoryStore and PostgresStore must behave identically.

The Postgres half never runs by default. It needs TIMEGLOBE_TEST_DATABASE_URL (the separate Neon
test branch) AND TIMEGLOBE_RUN_DB_TESTS=1 in the shell, and works in a scratch schema it drops.
"""

import os
import uuid
from datetime import date

import pytest

from timeglobe_pipeline import check, config
from timeglobe_pipeline.bipm_api import Series
from timeglobe_pipeline.labs import load_labs
from timeglobe_pipeline.migrate import apply_pending, discover
from timeglobe_pipeline.store import (
    Counts,
    MemoryStore,
    OffsetRow,
    PostgresStore,
    RetractedRow,
    StoredIssue,
    plan_retraction,
    plan_rows,
    rows_to_series,
    series_rows,
)

TEST_DB = config.env_value("TIMEGLOBE_TEST_DATABASE_URL")
DB_ENABLED = bool(TEST_DB) and os.environ.get("TIMEGLOBE_RUN_DB_TESTS") == "1"

LABS = load_labs()


def series(*pairs, unc=None):
    mjd = [m for m, _ in pairs]
    return Series("s", mjd, [v for _, v in pairs], unc or [None] * len(pairs))


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DB_ENABLED, reason="database test: needs TIMEGLOBE_TEST_DATABASE_URL and TIMEGLOBE_RUN_DB_TESTS=1"
            ),
        ),
    ]
)
def store(request):
    if request.param == "memory":
        yield MemoryStore()
        return
    import psycopg

    assert TEST_DB != config.env_value("DATABASE_URL"), "test URL must not be DATABASE_URL"
    schema = f"tg_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute(f"create schema {schema}")
        try:
            conn.execute(f"set search_path to {schema}")
            apply_pending(conn, discover())
            yield PostgresStore(conn)
        finally:
            conn.execute(f"drop schema {schema} cascade")


# --- pure planning ----------------------------------------------------------------------------


def test_plan_rows_splits_inserts_updates_and_unchanged():
    inserts, updates, unchanged = plan_rows({1: "a", 2: "b"}, {1: "a", 2: "B", 3: "c"})
    assert inserts == [(3, "c")] and updates == [(2, "B")] and unchanged == 1


def test_series_rows_attach_the_issue_and_rows_round_trip():
    s = series((10, 1.5), (15, -2.0), unc=[None, 0.4])
    assert series_rows(s, {15: 454}) == {10: (1.5, None, None), 15: (-2.0, 0.4, 454)}
    back = rows_to_series("s", [OffsetRow(10, 1.5, None, None), OffsetRow(15, -2.0, 0.4, 454)])
    assert (back.mjd, back.value_ns, back.unc_ns) == (s.mjd, s.value_ns, s.unc_ns)


# --- labs and offsets -------------------------------------------------------------------------


def test_upsert_labs_counts_added_unchanged_and_changed(store):
    assert store.upsert_labs(LABS) == Counts(len(LABS), 0)
    assert store.upsert_labs(LABS) == Counts(0, 0)
    from dataclasses import replace

    moved = [replace(LABS[0], city="Elsewhere")] + LABS[1:]
    assert store.upsert_labs(moved) == Counts(0, 1)


def test_offsets_report_added_changed_and_unchanged_rows(store):
    store.upsert_labs(LABS)
    assert store.upsert_offsets("NIST", "utc", series((10, 1.0), (15, 2.0))) == Counts(2, 0)
    assert store.upsert_offsets("NIST", "utc", series((10, 1.0), (15, 2.0))) == Counts(0, 0)
    # BIPM corrects one value and a new date arrives
    assert store.upsert_offsets("NIST", "utc", series((10, 1.0), (15, 2.5), (20, 3.0))) == Counts(1, 1)
    rows = store.load_series("utc")["NIST"]
    assert [(r.mjd, r.value_ns) for r in rows] == [(10, 1.0), (15, 2.5), (20, 3.0)]


def test_a_missing_date_is_an_absent_row_never_a_zero(store):
    store.upsert_labs(LABS)
    store.upsert_offsets("NIST", "utc", series((10, 1.0), (20, 3.0)))
    assert [r.mjd for r in store.load_series("utc")["NIST"]] == [10, 20]


def test_offsets_keep_the_circular_t_issue_they_came_from(store):
    store.upsert_labs(LABS)
    store.save_issue(StoredIssue(454, "a" * 32, "a" * 32, "body"))
    store.upsert_offsets("AZ", "utc", series((60949, 239.9), unc=[7.1]), {60949: 454})
    (row,) = store.load_series("utc")["AZ"]
    assert (row.value_ns, row.uncertainty_ns, row.circular_t_no) == (239.9, 7.1, 454)


def test_scales_are_kept_apart(store):
    store.upsert_labs(LABS)
    store.upsert_offsets("NIST", "utc", series((10, 1.0)))
    store.replace_rapid("NIST", series((11, 9.0)))
    assert [r.mjd for r in store.load_series("utc")["NIST"]] == [10]
    assert [r.mjd for r in store.load_series("utcr")["NIST"]] == [11]


# --- rapid values -----------------------------------------------------------------------------


def test_replace_rapid_replaces_the_labs_whole_rapid_tail(store):
    store.upsert_labs(LABS)
    assert store.replace_rapid("NIST", series((11, 1.0), (12, 2.0))) == (0, 2)
    assert store.replace_rapid("NIST", series((12, 2.5), (13, 3.0), (14, 4.0))) == (2, 3)
    assert [(r.mjd, r.value_ns) for r in store.load_series("utcr")["NIST"]] == [(12, 2.5), (13, 3.0), (14, 4.0)]


def test_drop_superseded_rapid_removes_days_a_circular_t_now_covers(store):
    store.upsert_labs(LABS)
    store.replace_rapid("NIST", series((11, 1.0), (12, 2.0), (13, 3.0)))
    store.replace_rapid("OP", series((11, 1.0), (14, 4.0)))
    assert store.drop_superseded_rapid(12) == 3
    assert [r.mjd for r in store.load_series("utcr")["NIST"]] == [13]
    assert [r.mjd for r in store.load_series("utcr")["OP"]] == [14]


# --- GNSS and clocks --------------------------------------------------------------------------


def test_gnss_counts_and_round_trip(store):
    s = series((10, -1.0), (11, -2.0), unc=[1.4, 1.5])
    assert store.upsert_gnss("gps", s) == Counts(2, 0)
    assert store.upsert_gnss("gps", s) == Counts(0, 0)
    assert store.upsert_gnss("gps", series((10, -1.0), (11, -2.5), unc=[1.4, 1.5])) == Counts(0, 1)
    loaded = store.load_gnss()["gps"]
    assert (loaded.mjd, loaded.value_ns, loaded.unc_ns) == ([10, 11], [-1.0, -2.5], [1.4, 1.5])


def test_clock_counts_per_month_and_the_latest_month_wins(store):
    store.upsert_labs(LABS)
    assert store.save_clock_counts(date(2026, 10, 1), {"USNO": 60, "OP": 5}) == Counts(2, 0)
    assert store.save_clock_counts(date(2026, 11, 1), {"USNO": 63, "OP": 5}) == Counts(2, 0)
    assert store.save_clock_counts(date(2026, 11, 1), {"USNO": 64, "OP": 5}) == Counts(0, 1)
    assert store.load_clock_counts() == {"USNO": 64, "OP": 5}


# --- issues and runs --------------------------------------------------------------------------


def test_issues_round_trip_and_mark_checked_updates_only_the_listed_checksum(store):
    store.save_issue(StoredIssue(465, "a" * 32, "b" * 32, "body"))
    store.mark_checked(465, "c" * 32)
    assert store.stored_issues() == {465: StoredIssue(465, "a" * 32, "c" * 32, "body")}
    store.save_issue(StoredIssue(465, "d" * 32, "c" * 32, "new body"))
    assert store.stored_issues()[465].body == "new body"


def test_last_ingested_issue_counts_only_ok_daily_runs_with_an_issue(store):
    assert store.last_ingested_issue() is None
    failed = store.start_run("daily")
    store.finish_run(failed, status="failed", rows_added=0, rows_changed=0, circular_t_no=466, details={}, error="x")
    weekly = store.start_run("weekly")
    store.finish_run(weekly, status="ok", rows_added=0, rows_changed=0, circular_t_no=470, details={})
    assert store.last_ingested_issue() is None
    ok = store.start_run("daily")
    store.finish_run(ok, status="ok", rows_added=3, rows_changed=1, circular_t_no=465, details={"flags": {"AZ": ["x"]}})
    noop = store.start_run("daily")
    store.finish_run(noop, status="ok", rows_added=0, rows_changed=0, circular_t_no=None, details={"flags": {}})
    assert store.last_ingested_issue() == 465
    assert store.latest_details("daily") == {"flags": {}}
    assert store.latest_details("monthly") == {}


# --- retraction: a value a revised source no longer contains is hidden, never deleted -----------


def test_plan_retraction_picks_only_active_rows_the_source_dropped():
    active = {1: (1.0, None), 2: (2.0, None), 3: (3.0, None)}
    assert plan_retraction(active, {1, 3}) == ([2], False)
    assert plan_retraction(active, {1, 2, 3}) == ([], False)


def test_plan_retraction_refuses_a_mass_retraction_but_allows_a_handful():
    active = {m: (1.0, None) for m in range(100)}
    missing, blocked = plan_retraction(active, set(range(10)))
    assert len(missing) == 90 and blocked  # a truncated response must not erase a history
    assert plan_retraction(active, set(range(95))) == ([95, 96, 97, 98, 99], False)


def test_retracting_hides_a_row_but_never_deletes_it(store):
    store.upsert_labs(LABS)
    store.save_issue(StoredIssue(465, "a" * 32, "a" * 32, "body"))
    store.upsert_offsets("AZ", "utc", series((10, 1.0), (15, 2.0), (20, 3.0)), {15: 465, 20: 465})
    result = store.retract_missing("AZ", "utc", {10, 20})
    assert result.blocked == 0 and result.rows == (RetractedRow("AZ", 15, 2.0, 465),)
    assert [r.mjd for r in store.load_series("utc")["AZ"]] == [10, 20]
    assert [(r.mjd, r.value_ns, r.circular_t_no) for r in store.load_retracted("utc")["AZ"]] == [(15, 2.0, 465)]
    assert store.retract_missing("AZ", "utc", {10, 20}).rows == ()  # already retracted: no repeat


def test_a_retracted_date_that_comes_back_is_restored_in_place(store):
    store.upsert_labs(LABS)
    store.upsert_offsets("NIST", "utc", series((10, 1.0), (15, 2.0)))
    store.retract_missing("NIST", "utc", {10})
    assert store.upsert_offsets("NIST", "utc", series((10, 1.0), (15, 2.0))) == Counts(0, 1)
    assert [r.mjd for r in store.load_series("utc")["NIST"]] == [10, 15]
    assert store.load_retracted("utc") == {}


def test_a_mass_retraction_is_refused_and_nothing_changes(store):
    store.upsert_labs(LABS)
    long = Series("s", list(range(1000, 1100)), [0.1] * 100, [None] * 100)
    store.upsert_offsets("NIST", "utc", long)
    result = store.retract_missing("NIST", "utc", set(range(1000, 1010)))
    assert result.rows == () and result.blocked == 90
    assert len(store.load_series("utc")["NIST"]) == 100 and store.load_retracted("utc") == {}


def test_retraction_touches_only_the_named_lab_and_scale(store):
    store.upsert_labs(LABS)
    store.upsert_offsets("NIST", "utc", series((10, 1.0), (15, 2.0)))
    store.upsert_offsets("OP", "utc", series((10, 1.0), (15, 2.0)))
    store.replace_rapid("NIST", series((20, 5.0)))
    store.retract_missing("NIST", "utc", set())
    assert "NIST" not in store.load_series("utc")
    assert [r.mjd for r in store.load_series("utc")["OP"]] == [10, 15]
    assert [r.mjd for r in store.load_series("utcr")["NIST"]] == [20]


def test_the_database_report_runs_and_counts_retracted_rows_separately(store):
    if not isinstance(store, PostgresStore):
        pytest.skip("the report reads Postgres; the memory store has no SQL")
    store.upsert_labs(LABS)
    store.upsert_offsets("NIST", "utc", series((10, 1.0), (15, 2.0)))
    store.retract_missing("NIST", "utc", {10})
    report = " | ".join(check.db_report(store.conn))
    assert "labs" in report and "offsets by scale (active / retracted)" in report
    assert "1 / 1" in report  # one active, one retracted
    assert "migrations: 1 core, 2 circular_t_issues, 3 retraction" in report


# --- the examined-mismatch record -------------------------------------------------------------


def test_confirm_mismatch_is_kept_until_the_body_changes(store):
    store.save_issue(StoredIssue(465, "a" * 32, "b" * 32, "body"))
    assert store.stored_issues()[465].mismatch_confirmed_for is None
    store.confirm_mismatch(465, "b" * 32)
    kept = store.stored_issues()[465]
    assert (kept.listed_md5, kept.mismatch_confirmed_for) == ("b" * 32, "b" * 32)
    store.mark_checked(465, "b" * 32)  # a daily check must not erase it
    assert store.stored_issues()[465].mismatch_confirmed_for == "b" * 32
    store.save_issue(StoredIssue(465, "c" * 32, "b" * 32, "revised body"))  # a new body resets it
    assert store.stored_issues()[465].mismatch_confirmed_for is None


# --- the date of the last data-changing run (meta.json's generated_at) ------------------------


def finished(store, source, status, details, added=0, changed=0):
    run = store.start_run(source)
    store.finish_run(run, status=status, rows_added=added, rows_changed=changed,
                     circular_t_no=None, details=details)


def test_last_data_change_date_follows_the_flag_and_falls_back_to_row_counts(store):
    assert store.last_data_change_date() is None
    finished(store, "daily", "ok", {"date": "2026-11-01"}, added=5)  # before the flag existed: counts
    assert store.last_data_change_date() == "2026-11-01"
    finished(store, "weekly", "ok", {"date": "2026-11-02", "data_changed": False})
    assert store.last_data_change_date() == "2026-11-01"  # a run that changed nothing does not move it
    finished(store, "daily", "failed", {"date": "2026-11-03", "data_changed": True}, added=9)
    assert store.last_data_change_date() == "2026-11-01"  # a failed run does not count
    finished(store, "weekly", "ok", {"date": "2026-11-05", "data_changed": True})  # rows 0, flag wins
    assert store.last_data_change_date() == "2026-11-05"
    finished(store, "monthly", "ok", {"date": "2026-11-08", "data_changed": False}, added=3)
    assert store.last_data_change_date() == "2026-11-05"  # the flag wins over the row counts
