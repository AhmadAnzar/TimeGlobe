"""The ingest jobs: daily (index, integrity, new issue), weekly (rapid UTC tail), monthly (clocks).

Each job takes a `Store` and an HTTP client and records itself in ingest_runs. A job that cannot
finish marks its run failed and raises, so the workflow fails and opens an issue. Per-lab problems
that leave the data incomplete (a lab's series could not be fetched) also fail the run, after
everything else has been written, so the next run retries; the writes are idempotent.

index_mismatch (a stored issue that is byte-identical on download while MD5SUMS lists another
checksum, as with issue 465) never blocks anything: it is flagged in the run's details.
"""

from dataclasses import dataclass
from datetime import date

from timeglobe_pipeline import bipm_api, circular_t_index, config
from timeglobe_pipeline.circular_t import ParseError, Section1, issue_by_mjd, parse_section1
from timeglobe_pipeline.clock_list import (
    CLOCK_DEFINITION,
    active_counts,
    clock_totals,
    parse_clocks,
)
from timeglobe_pipeline.http import FetchError, PoliteClient
from timeglobe_pipeline.issue_integrity import (
    classify,
    diff_issues,
    md5_of,
    needs_download,
    run_detail,
)
from timeglobe_pipeline.labs import Lab
from timeglobe_pipeline.prepare import prepare_series
from timeglobe_pipeline.rapid import rapid_tail
from timeglobe_pipeline.reconcile import needs_circular_t
from timeglobe_pipeline.snapshot import SnapshotInput, build_snapshot
from timeglobe_pipeline.store import Counts, StoredIssue, Store, rows_to_series

CLOCKS_URL = "https://webtai.bipm.org/database/clocklab.html"


class IngestError(Exception):
    pass


@dataclass(frozen=True)
class RunResult:
    run_id: int
    status: str
    rows_added: int
    rows_changed: int
    details: dict


def issue_url(number: int) -> str:
    return f"{circular_t_index.ISSUES_URL}cirt.{number}"


# --- Circular T issues -----------------------------------------------------------------------


def check_stored_issues(store: Store, client: PoliteClient, index: dict[int, str], details: dict) -> list[int]:
    """Compare every stored issue with MD5SUMS. Returns the issues whose body changed."""
    changed: list[int] = []
    for number, stored in sorted(store.stored_issues().items()):
        listed = index.get(number)
        if not needs_download(stored.md5, listed, stored.mismatch_confirmed_for):
            store.mark_checked(number, listed)
            if stored.md5 != listed:  # an index_mismatch already examined: flagged, not downloaded
                record = run_detail(number, "index_mismatch", stored.md5, listed, None)
                record["redownloaded"] = False
                details["issues"][str(number)] = record
            continue
        if listed is None:
            details["issues"][str(number)] = run_detail(number, "missing", stored.md5, None, None)
            store.mark_checked(number, None)
            continue
        body = client.get(issue_url(number))
        kind = classify(stored.md5, listed, body)
        if kind == "index_mismatch":
            record = run_detail(number, kind, stored.md5, listed, md5_of(body))
            record["redownloaded"] = True
            details["issues"][str(number)] = record
            store.confirm_mismatch(number, listed)  # not downloaded again until the index entry changes
        else:
            text = body.decode("utf-8")
            diff = diff_issues(stored.body, text)
            details["issues"][str(number)] = run_detail(
                number, kind, stored.md5, listed, md5_of(body), diff
            )
            store.save_issue(StoredIssue(number, md5_of(body), listed, text))
            changed.append(number)
    return changed


def ensure_issue(
    store: Store, client: PoliteClient, index: dict[int, str],
    stored: dict[int, StoredIssue], number: int, details: dict,
) -> StoredIssue:
    """The stored issue, downloading and storing it first if needed. A checksum that does not match
    the index is flagged ("unverified") and the issue is kept: it never blocks."""
    if number in stored:
        return stored[number]
    body = client.get(issue_url(number))
    got, listed = md5_of(body), index.get(number)
    if listed is not None and got != listed:
        details["issues"][str(number)] = run_detail(number, "unverified", got, listed, got)
    issue = StoredIssue(number, got, listed, body.decode("utf-8"))
    store.save_issue(issue)
    stored[number] = issue
    return issue


def sections_covering(
    store: Store, client: PoliteClient, index: dict[int, str], stored: dict[int, StoredIssue],
    latest: int, window_start_mjd: int, details: dict,
) -> list[Section1]:
    """Parsed issues from the latest back to the first one that starts on or before the date, which
    is how far a series has to be rebuilt."""
    sections: list[Section1] = []
    number = latest
    while number in index:
        issue = ensure_issue(store, client, index, stored, number, details)
        try:
            section = parse_section1(issue.body)
        except ParseError as exc:
            raise IngestError(f"issue {number} cannot be parsed: {exc}") from exc
        sections.append(section)
        if section.mjd[0] <= window_start_mjd:
            break
        number -= 1
    return sections


# --- daily -----------------------------------------------------------------------------------


MAX_LISTED_RETRACTIONS = 200


def _retract(store: Store, lab: str, kept_mjds: list[int], details: dict) -> Counts:
    """Retract (never delete) stored values the source no longer contains, and list them."""
    result = store.retract_missing(lab, "utc", set(kept_mjds))
    if result.blocked:
        details["failed"].append(
            f"{lab}: {result.blocked} stored values are missing from the source, more than the "
            "retraction limit; nothing was retracted, check the source"
        )
        return Counts()
    if not result.rows:
        return Counts()
    details["retracted"][lab] = {
        "count": len(result.rows),
        "rows": [
            {"mjd": r.mjd, "value_ns": r.value_ns, "circular_t_no": r.circular_t_no}
            for r in result.rows[:MAX_LISTED_RETRACTIONS]
        ],
    }
    for row in result.rows:  # also on the revised issue's own record
        issue = details["issues"].get(str(row.circular_t_no))
        if issue is not None:
            issue["retracted_rows"] = issue.get("retracted_rows", 0) + 1
    return Counts(0, len(result.rows))


def _ingest_drift(
    store: Store, client: PoliteClient, index: dict[int, str], latest: int,
    labs: list[Lab], details: dict,
) -> Counts:
    known = {lab.code for lab in labs}
    status_of = {lab.code: lab.status for lab in labs}
    lab_counts = store.upsert_labs(labs)  # reference data: reported in details, not as data rows
    details["labs"] = {"added": lab_counts.added, "changed": lab_counts.changed}
    counts = Counts()

    fetched: dict[str, bipm_api.Series] = {}
    for code in bipm_api.fetch_labs(client):
        try:
            fetched[code] = bipm_api.fetch_utc(client, code)
        except bipm_api.ApiError as exc:
            # A lab that is not current (EE joined in 2026) can have no data yet; a current one cannot.
            bucket = "failed" if status_of.get(code) == "current" else "no_data"
            details[bucket].append(code if bucket == "no_data" else f"{code}: {exc}")
        except FetchError as exc:
            details["failed"].append(f"{code}: {exc}")

    stored = store.stored_issues()
    broken = [c for c, s in fetched.items() if c in known and s.mjd and needs_circular_t(s)]
    if broken:
        window = min(min(fetched[c].mjd) for c in broken)
        sections = sections_covering(store, client, index, stored, latest, window, details)
    else:
        ensure_issue(store, client, index, stored, latest, details)  # keep the newest issue on file
        sections = []

    latest_mjd = 0
    for code, api in fetched.items():
        prepared = prepare_series(code, api, sections, known)
        if prepared.flags:
            details["flags"][code] = list(prepared.flags)
        if prepared.series is None:
            continue
        nos = issue_by_mjd(sections, code) if prepared.source == "circular_t" else None
        counts += store.upsert_offsets(code, "utc", prepared.series, nos)
        counts += _retract(store, code, prepared.series.mjd, details)
        latest_mjd = max(latest_mjd, prepared.series.mjd[-1])

    try:
        for system, series in bipm_api.fetch_gnss(client).items():
            counts += store.upsert_gnss(system, series)
    except (FetchError, bipm_api.ApiError) as exc:
        details["failed"].append(f"gnss: {exc}")

    if latest_mjd:
        details["rapid_dropped"] = store.drop_superseded_rapid(latest_mjd)
    return counts


def daily(store: Store, client: PoliteClient, labs: list[Lab], today: date) -> RunResult:
    run_id = store.start_run("daily")
    details: dict = {"issues": {}, "flags": {}, "failed": [], "no_data": [], "retracted": {},
                     "date": today.isoformat()}
    counts = Counts()
    latest = None
    try:
        index = circular_t_index.fetch_index(client)
        latest = circular_t_index.latest_issue(index)
        details["circular_t_latest"] = latest
        changed = check_stored_issues(store, client, index, details)
        last = store.last_ingested_issue()
        do_ingest = last is None or latest > last or bool(changed)
        details["ingested"] = do_ingest
        if do_ingest:
            counts = _ingest_drift(store, client, index, latest, labs, details)
        else:
            # Nothing new: keep the data flags from the last full run so snapshots still carry them.
            details["flags"] = store.latest_details("daily").get("flags", {})
        details["data_changed"] = bool(counts.added or counts.changed or details.get("rapid_dropped"))
        status = "failed" if details["failed"] else "ok"
        error = "; ".join(details["failed"])[:2000] or None
    except Exception as exc:
        store.finish_run(run_id, status="failed", rows_added=counts.added, rows_changed=counts.changed,
                         circular_t_no=latest, details=details, error=repr(exc)[:2000])
        raise
    store.finish_run(run_id, status=status, rows_added=counts.added, rows_changed=counts.changed,
                     circular_t_no=latest if do_ingest else None, details=details, error=error)
    if status == "failed":
        raise IngestError(error)
    return RunResult(run_id, status, counts.added, counts.changed, details)


# --- weekly ----------------------------------------------------------------------------------


def _set_rapid(store: Store, existing: dict, lab: str, tail: bipm_api.Series) -> tuple[bool, int]:
    """Replace a lab's rapid tail only if it differs from what is stored. Returns (changed, rows
    inserted), so a week with no new days writes nothing and does not count as a data change."""
    stored = [(r.mjd, r.value_ns) for r in existing.get(lab, [])]
    if stored == list(zip(tail.mjd, tail.value_ns)):
        return False, 0
    _, inserted = store.replace_rapid(lab, tail)
    return True, inserted


def weekly(store: Store, client: PoliteClient, today: date, force: bool = False) -> RunResult:
    run_id = store.start_run("weekly")
    # rapid_empty: labs whose rapid series does not exist, with the date they were last asked. They
    # are skipped until MONTHLY_DAYS have passed, then asked again so a lab that gains one is found.
    details: dict = {"failed": [], "no_rapid": [], "skipped_no_rapid": [], "rapid_empty": {},
                     "rapid_changed": 0, "date": today.isoformat()}
    added = returned = kept = 0
    try:
        published = store.load_series("utc")
        if not published:
            raise IngestError("no published series in the database; run the daily job first")
        cutoff = max(rows[-1].mjd for rows in published.values())
        details["after_mjd"] = cutoff
        details["rapid_dropped"] = store.drop_superseded_rapid(cutoff)
        existing_rapid = store.load_series("utcr")  # after the drop, so the comparison is like for like
        previous_empty = store.latest_details("weekly").get("rapid_empty", {})
        for lab in sorted(published):
            last_asked = previous_empty.get(lab)
            if (not force and last_asked
                    and (today - date.fromisoformat(last_asked)).days < config.MONTHLY_DAYS):
                details["skipped_no_rapid"].append(lab)
                details["rapid_empty"][lab] = last_asked  # the window runs from the real request
                continue
            try:
                # Only the days after the latest Circular T date are kept, so only those are asked
                # for. mjd1 is the cutoff itself, so the request is right whether the API treats
                # it as inclusive or not; rapid_tail trims the one possible extra day.
                rapid = bipm_api.fetch_utc(client, lab, "utcr", mjd1=cutoff)
            except bipm_api.ApiError:
                details["no_rapid"].append(lab)  # no rapid series at all, e.g. a lab that stopped
                details["rapid_empty"][lab] = today.isoformat()
                changed, _ = _set_rapid(store, existing_rapid, lab, bipm_api.Series(lab, [], [], []))
                details["rapid_changed"] += changed
                continue
            except FetchError as exc:
                details["failed"].append(f"{lab}: {exc}")
                continue
            tail = rapid_tail(rapid, cutoff)
            returned += len(rapid.mjd)
            kept += len(tail.mjd)
            if not tail.mjd:
                # Nothing after the cutoff to keep. Not recorded in rapid_empty: the series exists and
                # its next days may simply not be published yet, so it is asked again next week.
                details["no_rapid"].append(lab)
            changed, inserted = _set_rapid(store, existing_rapid, lab, tail)
            details["rapid_changed"] += changed
            added += inserted
        details["data_changed"] = bool(details["rapid_changed"] or details["rapid_dropped"])
        details["rapid_points"] = {"returned": returned, "kept": kept}
        # If the API ignored mjd1 it sent whole histories: still correct, but not the saving intended.
        details["mjd1_ignored"] = returned > 1000 and returned > 5 * max(kept, 1)
        status = "failed" if details["failed"] else "ok"
        error = "; ".join(details["failed"])[:2000] or None
    except Exception as exc:
        store.finish_run(run_id, status="failed", rows_added=added, rows_changed=0,
                         circular_t_no=None, details=details, error=repr(exc)[:2000])
        raise
    store.finish_run(run_id, status=status, rows_added=added, rows_changed=0,
                     circular_t_no=None, details=details, error=error)
    if status == "failed":
        raise IngestError(error)
    return RunResult(run_id, status, added, 0, details)


# --- monthly ---------------------------------------------------------------------------------


def _monthly_skip(store: Store, today: date) -> dict | None:
    """Details for a skipped run if the clock list was fetched less than MONTHLY_DAYS days ago.
    The record of that fetch is the previous successful run's own details, so it survives a CI
    runner that starts without any saved pages; a skipped run carries it (and the clock totals)
    forward, which keeps the window measured from the real fetch."""
    previous = store.latest_details("monthly")
    fetched = previous.get("fetched_on") or previous.get("date")  # older runs only had "date"
    if not fetched or (today - date.fromisoformat(fetched)).days >= config.MONTHLY_DAYS:
        return None
    return {
        "date": today.isoformat(), "skipped": True, "fetched_on": fetched, "data_changed": False,
        "clocks": previous.get("clocks", {}),
        "reason": f"the clock list was fetched on {fetched}; it is fetched at most every "
                  f"{config.MONTHLY_DAYS} days",
    }


def monthly(store: Store, client: PoliteClient, labs: list[Lab], today: date, force: bool = False) -> RunResult:
    skip = None if force else _monthly_skip(store, today)
    run_id = store.start_run("monthly")
    if skip is not None:
        store.finish_run(run_id, status="ok", rows_added=0, rows_changed=0,
                         circular_t_no=None, details=skip)
        return RunResult(run_id, "ok", 0, 0, skip)
    details: dict = {"date": today.isoformat(), "fetched_on": today.isoformat()}
    counts = Counts()
    try:
        known = {lab.code for lab in labs}
        clocks = parse_clocks(client.get(CLOCKS_URL).decode("utf-8"))
        totals = clock_totals(clocks, known)  # computed from the page every run, never stored as a constant
        per_lab, _ = active_counts(clocks, known)
        store.upsert_labs(labs)
        counts = store.save_clock_counts(today.replace(day=1), {lab.code: per_lab.get(lab.code, 0) for lab in labs})
        details["data_changed"] = bool(counts.added or counts.changed)
        details["clocks"] = {
            "definition": CLOCK_DEFINITION,
            "total": totals.total,
            "in_labs": totals.in_labs,
            "unmapped": totals.unmapped,
            "stopped": totals.stopped,
        }
    except Exception as exc:
        store.finish_run(run_id, status="failed", rows_added=counts.added, rows_changed=counts.changed,
                         circular_t_no=None, details=details, error=repr(exc)[:2000])
        raise
    store.finish_run(run_id, status="ok", rows_added=counts.added, rows_changed=counts.changed,
                     circular_t_no=None, details=details)
    return RunResult(run_id, "ok", counts.added, counts.changed, details)


# --- snapshot (reads the database, no network) -----------------------------------------------


def snapshot_date(store: Store, today: date) -> str:
    """meta.json's generated_at: the date of the last run that changed data, not today. A day with
    nothing new therefore leaves the snapshot byte-identical and nothing is published. An empty
    store falls back to today."""
    return store.last_data_change_date() or today.isoformat()


def snapshot_files(store: Store, labs: list[Lab], generated_at: str) -> dict[str, bytes]:
    utc = store.load_series("utc")
    if not utc:
        raise IngestError("no data to build a snapshot from")
    series = {lab: rows_to_series(f"UTC-UTC({lab})", rows) for lab, rows in utc.items()}
    sources = {
        lab: "circular_t" if any(r.circular_t_no is not None for r in rows) else "api"
        for lab, rows in utc.items()
    }
    rapid = {lab: rows_to_series(f"UTCR-UTC({lab})", rows) for lab, rows in store.load_series("utcr").items()}
    daily_details = store.latest_details("daily")
    monthly_details = store.latest_details("monthly")
    return build_snapshot(
        SnapshotInput(
            labs=labs,
            series=series,
            sources=sources,
            gnss=store.load_gnss(),
            clocks=store.load_clock_counts(),
            circular_t_latest=store.last_ingested_issue() or 0,
            generated_at=generated_at,
            rapid=rapid,
            flags={code: tuple(f) for code, f in daily_details.get("flags", {}).items()},
            unmapped_clocks=monthly_details.get("clocks", {}).get("unmapped", {}),
        )
    )
