"""The database writer: one interface, a Postgres implementation and an in-memory twin.

The ingest jobs only talk to `Store`. `PostgresStore` is the real thing and is the only code that
runs SQL; `MemoryStore` behaves the same and is what the tests use, so the job logic is checked
without a database. Both are checked against the same contract tests.

Writers return how many rows were added and how many existing rows were changed (a BIPM
correction), which becomes ingest_runs.rows_added / rows_changed. A value a revised source no
longer contains is retracted (retracted_at set), never deleted, and reads skip retracted rows. Nothing here connects by itself:
a connection is passed in, and the job entry points refuse to open one without an explicit opt-in.
"""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from timeglobe_pipeline.bipm_api import Series
from timeglobe_pipeline.labs import Lab


@dataclass(frozen=True)
class Counts:
    added: int = 0
    changed: int = 0

    def __add__(self, other: "Counts") -> "Counts":
        return Counts(self.added + other.added, self.changed + other.changed)


@dataclass(frozen=True)
class StoredIssue:
    issue: int
    md5: str  # of the body as downloaded
    listed_md5: str | None  # what MD5SUMS listed when last checked
    body: str
    # the listed checksum for which a download found this body unchanged (index_mismatch)
    mismatch_confirmed_for: str | None = None


@dataclass(frozen=True)
class OffsetRow:
    mjd: int
    value_ns: float
    uncertainty_ns: float | None
    circular_t_no: int | None


@dataclass(frozen=True)
class RetractedRow:
    lab: str
    mjd: int
    value_ns: float
    circular_t_no: int | None


@dataclass(frozen=True)
class Retraction:
    rows: tuple[RetractedRow, ...] = ()
    blocked: int = 0  # rows that WOULD have been retracted but exceeded the safety limit: none were


RETRACTION_FLOOR = 10  # always allowed per lab and run
RETRACTION_FRACTION = 0.02  # or this share of the lab's active rows, whichever is larger


def plan_retraction(active: dict[int, tuple], keep: set[int]) -> tuple[list[int], bool]:
    """Dates to retract (active rows the source no longer contains) and whether that is too many.
    A truncated or failed response would otherwise retract a whole history, so a large number is
    refused for a person to look at; nothing is retracted then."""
    missing = sorted(m for m in active if m not in keep)
    limit = max(RETRACTION_FLOOR, int(len(active) * RETRACTION_FRACTION))
    return missing, len(missing) > limit


def plan_rows(existing: dict, incoming: dict) -> tuple[list, list, int]:
    """Split incoming {key: row} against existing {key: row} into (inserts, updates, unchanged).
    Inserts and updates are lists of (key, row). Pure, so it can be tested without a database."""
    inserts, updates, unchanged = [], [], 0
    for key, row in incoming.items():
        if key not in existing:
            inserts.append((key, row))
        elif existing[key] != row:
            updates.append((key, row))
        else:
            unchanged += 1
    return inserts, updates, unchanged


def series_rows(series: Series, circular_t_nos: dict[int, int] | None = None) -> dict[int, tuple]:
    nos = circular_t_nos or {}
    return {
        m: (v, u, nos.get(m))
        for m, v, u in zip(series.mjd, series.value_ns, series.unc_ns)
    }


def rows_to_series(name: str, rows: list[OffsetRow]) -> Series:
    return Series(
        name, [r.mjd for r in rows], [r.value_ns for r in rows], [r.uncertainty_ns for r in rows]
    )


class Store(Protocol):
    def upsert_labs(self, labs: list[Lab]) -> Counts: ...
    def upsert_offsets(
        self, lab: str, scale: str, series: Series, circular_t_nos: dict[int, int] | None = None
    ) -> Counts: ...
    def retract_missing(self, lab: str, scale: str, keep: set[int]) -> Retraction: ...
    def replace_rapid(self, lab: str, tail: Series) -> tuple[int, int]: ...  # (deleted, inserted)
    def drop_superseded_rapid(self, latest_mjd: int) -> int: ...
    def upsert_gnss(self, system: str, series: Series) -> Counts: ...
    def save_clock_counts(self, month: date, counts: dict[str, int]) -> Counts: ...
    def stored_issues(self) -> dict[int, StoredIssue]: ...
    def save_issue(self, issue: StoredIssue) -> None: ...
    def mark_checked(self, issue: int, listed_md5: str | None) -> None: ...
    def confirm_mismatch(self, issue: int, listed_md5: str) -> None: ...
    def last_ingested_issue(self) -> int | None: ...
    def start_run(self, source: str) -> int: ...
    def finish_run(
        self, run_id: int, *, status: str, rows_added: int, rows_changed: int,
        circular_t_no: int | None, details: dict, error: str | None = None,
    ) -> None: ...
    def latest_details(self, source: str) -> dict: ...
    def last_data_change_date(self) -> str | None: ...
    def load_series(self, scale: str) -> dict[str, list[OffsetRow]]: ...  # never retracted rows
    def load_retracted(self, scale: str) -> dict[str, list[OffsetRow]]: ...
    def load_gnss(self) -> dict[str, Series]: ...
    def load_clock_counts(self) -> dict[str, int]: ...


# ---------------------------------------------------------------------------------------------
class MemoryStore:
    """Same behaviour as PostgresStore, in dictionaries."""

    def __init__(self) -> None:
        self.labs: dict[str, tuple] = {}
        self.offsets: dict[tuple[str, str], dict[int, tuple]] = {}
        self.gnss: dict[str, dict[int, tuple]] = {}
        self.clock_counts: dict[date, dict[str, int]] = {}
        self.issues: dict[int, StoredIssue] = {}
        self.runs: list[dict] = []

    def upsert_labs(self, labs):
        incoming = {
            lab.code: (lab.name, lab.city, lab.country, lab.iso2, lab.lat, lab.lon,
                       lab.year_start, lab.year_stop, lab.status)
            for lab in labs
        }
        inserts, updates, _ = plan_rows(self.labs, incoming)
        self.labs.update(dict(inserts + updates))
        return Counts(len(inserts), len(updates))

    def upsert_offsets(self, lab, scale, series, circular_t_nos=None):
        if lab not in self.labs:
            raise KeyError(f"unknown lab {lab}")  # the foreign key in Postgres
        table = self.offsets.setdefault((lab, scale), {})
        incoming = {m: (*row, False) for m, row in series_rows(series, circular_t_nos).items()}
        inserts, updates, _ = plan_rows(table, incoming)  # a retracted row differs, so it is restored
        table.update(dict(inserts + updates))
        return Counts(len(inserts), len(updates))

    def retract_missing(self, lab, scale, keep):
        table = self.offsets.get((lab, scale), {})
        active = {m: row for m, row in table.items() if not row[3]}
        missing, blocked = plan_retraction(active, keep)
        if blocked:
            return Retraction(blocked=len(missing))
        for m in missing:
            v, u, no, _ = table[m]
            table[m] = (v, u, no, True)
        return Retraction(tuple(RetractedRow(lab, m, active[m][0], active[m][2]) for m in missing))

    def replace_rapid(self, lab, tail):
        if lab not in self.labs:
            raise KeyError(f"unknown lab {lab}")
        old = self.offsets.pop((lab, "utcr"), {})
        self.offsets[(lab, "utcr")] = {m: (*row, False) for m, row in series_rows(tail).items()}
        return len(old), len(tail.mjd)

    def drop_superseded_rapid(self, latest_mjd):
        dropped = 0
        for (lab, scale), table in self.offsets.items():
            if scale == "utcr":
                gone = [m for m in table if m <= latest_mjd]
                for m in gone:
                    del table[m]
                dropped += len(gone)
        return dropped

    def upsert_gnss(self, system, series):
        table = self.gnss.setdefault(system, {})
        incoming = {m: (v, u) for m, v, u in zip(series.mjd, series.value_ns, series.unc_ns)}
        inserts, updates, _ = plan_rows(table, incoming)
        table.update(dict(inserts + updates))
        return Counts(len(inserts), len(updates))

    def save_clock_counts(self, month, counts):
        for lab in counts:
            if lab not in self.labs:
                raise KeyError(f"unknown lab {lab}")
        table = self.clock_counts.setdefault(month, {})
        inserts, updates, _ = plan_rows(table, counts)
        table.update(dict(inserts + updates))
        return Counts(len(inserts), len(updates))

    def stored_issues(self):
        return dict(self.issues)

    def save_issue(self, issue):
        self.issues[issue.issue] = issue

    def mark_checked(self, issue, listed_md5):
        old = self.issues[issue]
        self.issues[issue] = StoredIssue(
            old.issue, old.md5, listed_md5, old.body, old.mismatch_confirmed_for
        )

    def confirm_mismatch(self, issue, listed_md5):
        old = self.issues[issue]
        self.issues[issue] = StoredIssue(old.issue, old.md5, listed_md5, old.body, listed_md5)

    def last_ingested_issue(self):
        done = [
            r["circular_t_no"] for r in self.runs
            if r["source"] == "daily" and r["status"] == "ok" and r["circular_t_no"] is not None
        ]
        return max(done) if done else None

    def start_run(self, source):
        self.runs.append({"source": source, "status": "running", "rows_added": 0, "rows_changed": 0,
                          "circular_t_no": None, "details": {}, "error": None})
        return len(self.runs)

    def finish_run(self, run_id, *, status, rows_added, rows_changed, circular_t_no, details, error=None):
        self.runs[run_id - 1].update(
            status=status, rows_added=rows_added, rows_changed=rows_changed,
            circular_t_no=circular_t_no, details=details, error=error,
        )

    def latest_details(self, source):
        ok = [r["details"] for r in self.runs if r["source"] == source and r["status"] == "ok"]
        return ok[-1] if ok else {}

    def last_data_change_date(self):
        """ISO date of the last ok run that changed data: its data_changed flag when it has one,
        otherwise (runs from before the flag existed) whether it added or changed rows."""
        dates = []
        for run in self.runs:
            if run["status"] != "ok" or not run["details"].get("date"):
                continue
            details = run["details"]
            changed = details["data_changed"] if "data_changed" in details else (
                run["rows_added"] > 0 or run["rows_changed"] > 0
            )
            if changed:
                dates.append(details["date"])
        return max(dates) if dates else None

    def load_series(self, scale):
        return self._load(scale, retracted=False)

    def load_retracted(self, scale):
        return self._load(scale, retracted=True)

    def _load(self, scale, retracted):
        out: dict[str, list[OffsetRow]] = {}
        for (lab, s), table in sorted(self.offsets.items()):
            rows = [OffsetRow(m, *table[m][:3]) for m in sorted(table) if table[m][3] == retracted]
            if s == scale and rows:
                out[lab] = rows
        return out

    def load_gnss(self):
        return {
            system: Series(f"UTC-{system}", sorted(t), [t[m][0] for m in sorted(t)],
                           [t[m][1] for m in sorted(t)])
            for system, t in sorted(self.gnss.items()) if t
        }

    def load_clock_counts(self):
        return dict(self.clock_counts[max(self.clock_counts)]) if self.clock_counts else {}


# ---------------------------------------------------------------------------------------------
class PostgresStore:
    """The real writer. `conn` is an open psycopg connection with autocommit on; each method that
    writes does so in its own transaction."""

    def __init__(self, conn) -> None:
        self.conn = conn

    def upsert_labs(self, labs):
        existing = {
            r[0]: tuple(r[1:]) for r in self.conn.execute(
                "select code, name, city, country_bipm, iso2, lat, lon, year_start, year_stop, "
                "status from labs"
            )
        }
        incoming = {
            lab.code: (lab.name, lab.city, lab.country, lab.iso2, lab.lat, lab.lon,
                       lab.year_start, lab.year_stop, lab.status)
            for lab in labs
        }
        inserts, updates, _ = plan_rows(existing, incoming)
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.executemany(
                "insert into labs (code, name, city, country_bipm, iso2, lat, lon, year_start, "
                "year_stop, status) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(k, *row) for k, row in inserts],
            )
            cur.executemany(
                "update labs set name=%s, city=%s, country_bipm=%s, iso2=%s, lat=%s, lon=%s, "
                "year_start=%s, year_stop=%s, status=%s where code=%s",
                [(*row, k) for k, row in updates],
            )
        return Counts(len(inserts), len(updates))

    def upsert_offsets(self, lab, scale, series, circular_t_nos=None):
        if not series.mjd:
            return Counts()
        existing = {
            m: (v, u, no, retracted) for m, v, u, no, retracted in self.conn.execute(
                "select mjd, value_ns, uncertainty_ns, circular_t_no, retracted_at is not null "
                "from offsets where lab=%s and scale=%s and mjd between %s and %s",
                (lab, scale, min(series.mjd), max(series.mjd)),
            )
        }
        incoming = {m: (*row, False) for m, row in series_rows(series, circular_t_nos).items()}
        inserts, updates, _ = plan_rows(existing, incoming)  # a retracted row differs: restored
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.executemany(
                "insert into offsets (lab, scale, mjd, value_ns, uncertainty_ns, circular_t_no) "
                "values (%s,%s,%s,%s,%s,%s)",
                [(lab, scale, m, *row[:3]) for m, row in inserts],
            )
            cur.executemany(
                "update offsets set value_ns=%s, uncertainty_ns=%s, circular_t_no=%s, "
                "retracted_at=null where lab=%s and scale=%s and mjd=%s",
                [(*row[:3], lab, scale, m) for m, row in updates],
            )
        return Counts(len(inserts), len(updates))

    def retract_missing(self, lab, scale, keep):
        active = {
            m: (v, no) for m, v, no in self.conn.execute(
                "select mjd, value_ns, circular_t_no from offsets "
                "where lab=%s and scale=%s and retracted_at is null", (lab, scale)
            )
        }
        missing, blocked = plan_retraction(active, keep)
        if blocked:
            return Retraction(blocked=len(missing))
        if missing:
            with self.conn.transaction():
                self.conn.execute(
                    "update offsets set retracted_at=now() where lab=%s and scale=%s "
                    "and mjd = any(%s) and retracted_at is null", (lab, scale, missing)
                )
        return Retraction(tuple(RetractedRow(lab, m, active[m][0], active[m][1]) for m in missing))

    def replace_rapid(self, lab, tail):
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute("delete from offsets where lab=%s and scale='utcr'", (lab,))
            deleted = cur.rowcount
            cur.executemany(
                "insert into offsets (lab, scale, mjd, value_ns, uncertainty_ns) "
                "values (%s,'utcr',%s,%s,%s)",
                [(lab, m, v, u) for m, v, u in zip(tail.mjd, tail.value_ns, tail.unc_ns)],
            )
        return deleted, len(tail.mjd)

    def drop_superseded_rapid(self, latest_mjd):
        with self.conn.transaction():
            return self.conn.execute(
                "delete from offsets where scale='utcr' and mjd <= %s", (latest_mjd,)
            ).rowcount

    def upsert_gnss(self, system, series):
        if not series.mjd:
            return Counts()
        existing = {
            m: (v, u) for m, v, u in self.conn.execute(
                "select mjd, value_ns, uncertainty_ns from gnss_offsets "
                "where system=%s and mjd between %s and %s",
                (system, min(series.mjd), max(series.mjd)),
            )
        }
        incoming = {m: (v, u) for m, v, u in zip(series.mjd, series.value_ns, series.unc_ns)}
        inserts, updates, _ = plan_rows(existing, incoming)
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.executemany(
                "insert into gnss_offsets (system, mjd, value_ns, uncertainty_ns) values (%s,%s,%s,%s)",
                [(system, m, *row) for m, row in inserts],
            )
            cur.executemany(
                "update gnss_offsets set value_ns=%s, uncertainty_ns=%s where system=%s and mjd=%s",
                [(*row, system, m) for m, row in updates],
            )
        return Counts(len(inserts), len(updates))

    def save_clock_counts(self, month, counts):
        existing = {
            lab: n for lab, n in self.conn.execute(
                "select lab, n from clock_counts where month=%s", (month,)
            )
        }
        inserts, updates, _ = plan_rows(existing, counts)
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.executemany(
                "insert into clock_counts (lab, month, n) values (%s,%s,%s)",
                [(lab, month, n) for lab, n in inserts],
            )
            cur.executemany(
                "update clock_counts set n=%s where lab=%s and month=%s",
                [(n, lab, month) for lab, n in updates],
            )
        return Counts(len(inserts), len(updates))

    def stored_issues(self):
        return {
            r[0]: StoredIssue(r[0], r[1], r[2], r[3], r[4]) for r in self.conn.execute(
                "select issue, md5, listed_md5, body, mismatch_confirmed_for from circular_t_issues"
            )
        }

    def save_issue(self, issue):
        with self.conn.transaction():
            self.conn.execute(
                "insert into circular_t_issues (issue, md5, listed_md5, body, mismatch_confirmed_for) "
                "values (%s,%s,%s,%s,%s) on conflict (issue) do update set md5=excluded.md5, "
                "listed_md5=excluded.listed_md5, body=excluded.body, "
                "mismatch_confirmed_for=excluded.mismatch_confirmed_for, fetched_at=now(), checked_at=now()",
                (issue.issue, issue.md5, issue.listed_md5, issue.body, issue.mismatch_confirmed_for),
            )

    def mark_checked(self, issue, listed_md5):
        with self.conn.transaction():
            self.conn.execute(
                "update circular_t_issues set listed_md5=%s, checked_at=now() where issue=%s",
                (listed_md5, issue),
            )

    def confirm_mismatch(self, issue, listed_md5):
        with self.conn.transaction():
            self.conn.execute(
                "update circular_t_issues set listed_md5=%s, mismatch_confirmed_for=%s, checked_at=now() "
                "where issue=%s",
                (listed_md5, listed_md5, issue),
            )

    def last_ingested_issue(self):
        row = self.conn.execute(
            "select max(circular_t_no) from ingest_runs where source='daily' and status='ok'"
        ).fetchone()
        return row[0] if row else None

    def start_run(self, source):
        with self.conn.transaction():
            return self.conn.execute(
                "insert into ingest_runs (source, status) values (%s, 'running') returning id",
                (source,),
            ).fetchone()[0]

    def finish_run(self, run_id, *, status, rows_added, rows_changed, circular_t_no, details, error=None):
        from psycopg.types.json import Jsonb

        with self.conn.transaction():
            self.conn.execute(
                "update ingest_runs set finished_at=now(), status=%s, rows_added=%s, rows_changed=%s, "
                "circular_t_no=%s, details=%s, error=%s where id=%s",
                (status, rows_added, rows_changed, circular_t_no, Jsonb(details), error, run_id),
            )

    def latest_details(self, source):
        row = self.conn.execute(
            "select details from ingest_runs where source=%s and status='ok' order by id desc limit 1",
            (source,),
        ).fetchone()
        return row[0] if row else {}

    def last_data_change_date(self):
        row = self.conn.execute(
            "select max(details->>'date') from ingest_runs where status = 'ok' "
            "and details->>'date' is not null and ("
            "(details->>'data_changed' is not null and (details->>'data_changed')::boolean) "
            "or (details->>'data_changed' is null and (rows_added > 0 or rows_changed > 0)))"
        ).fetchone()
        return row[0] if row else None

    def load_series(self, scale):
        return self._load(scale, "is null")

    def load_retracted(self, scale):
        return self._load(scale, "is not null")

    def _load(self, scale, retracted_clause):
        out: dict[str, list[OffsetRow]] = {}
        for lab, mjd, value, unc, no in self.conn.execute(
            "select lab, mjd, value_ns, uncertainty_ns, circular_t_no from offsets "
            f"where scale=%s and retracted_at {retracted_clause} order by lab, mjd", (scale,)
        ):
            out.setdefault(lab, []).append(OffsetRow(mjd, value, unc, no))
        return out

    def load_gnss(self):
        rows: dict[str, list[tuple]] = {}
        for system, mjd, value, unc in self.conn.execute(
            "select system, mjd, value_ns, uncertainty_ns from gnss_offsets order by system, mjd"
        ):
            rows.setdefault(system, []).append((mjd, value, unc))
        return {
            s: Series(f"UTC-{s}", [r[0] for r in r_], [r[1] for r in r_], [r[2] for r in r_])
            for s, r_ in rows.items()
        }

    def load_clock_counts(self):
        return {
            lab: n for lab, n in self.conn.execute(
                "select lab, n from clock_counts where month = (select max(month) from clock_counts)"
            )
        }
