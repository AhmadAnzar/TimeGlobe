import os
import re
import uuid

import pytest

from timeglobe_pipeline import config
from timeglobe_pipeline.migrate import (
    MIGRATIONS_DIR,
    Migration,
    MigrationError,
    apply_pending,
    discover,
    pending,
)


def make_dir(tmp_path, name, *files):
    directory = tmp_path / name
    directory.mkdir()
    for file in files:
        (directory / file).write_text(f"-- {file}\nselect 1;\n", encoding="utf-8")
    return directory


def test_real_migrations_are_numbered_from_one_without_gaps():
    migrations = discover(MIGRATIONS_DIR)
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))
    assert migrations[0].name == "core"


def test_core_migration_creates_the_phase_2_tables():
    sql = discover(MIGRATIONS_DIR)[0].sql
    created = set(re.findall(r"create table (\w+)", sql))
    assert created == {"labs", "offsets", "clock_counts", "gnss_offsets", "ingest_runs"}
    assert "primary key (lab, scale, mjd)" in sql  # a re-ingest overwrites in place
    assert "references labs (code)" in sql


def test_issue_table_migration_stores_checksums_and_links_offsets_to_issues():
    migrations = discover(MIGRATIONS_DIR)
    assert [m.name for m in migrations][:2] == ["core", "circular_t_issues"]
    sql = migrations[1].sql
    assert "create table circular_t_issues" in sql and "md5         char(32) not null" in sql
    assert "foreign key (circular_t_no) references circular_t_issues (issue)" in sql


def test_retraction_migration_adds_a_nullable_timestamp_and_never_deletes():
    migrations = discover(MIGRATIONS_DIR)
    assert migrations[2].name == "retraction"
    sql = " ".join(
        line for line in migrations[2].sql.lower().splitlines() if not line.strip().startswith("--")
    )  # the statements, not the comments
    assert "add column retracted_at timestamptz;" in sql  # nullable: no constraint on the column
    assert "delete" not in sql and "drop" not in sql


def test_discover_sorts_and_rejects_gaps_and_odd_names(tmp_path):
    ordered = discover(make_dir(tmp_path, "ok", "0002_b.sql", "0001_a.sql"))
    assert [m.version for m in ordered] == [1, 2]
    with pytest.raises(MigrationError, match="gaps"):
        discover(make_dir(tmp_path, "gap", "0001_a.sql", "0003_c.sql"))
    with pytest.raises(MigrationError, match="NNNN_name"):
        discover(make_dir(tmp_path, "odd", "0001_a.sql", "notes.txt"))


def test_a_missing_migrations_folder_explains_the_editable_install(tmp_path):
    with pytest.raises(MigrationError, match="pip install -e"):
        discover(tmp_path / "nowhere")


def test_pending_returns_only_unapplied_migrations():
    a, b = Migration(1, "a", "select 1"), Migration(2, "b", "select 2")
    assert pending([a, b], {}) == [a, b]
    assert pending([a, b], {1: a.checksum}) == [b]
    assert pending([a, b], {1: a.checksum, 2: b.checksum}) == []


def test_an_applied_migration_that_was_edited_is_an_error():
    a = Migration(1, "a", "select 1")
    with pytest.raises(MigrationError, match="edited after it was applied"):
        pending([a], {1: "0" * 64})


def test_a_database_ahead_of_the_checkout_is_an_error():
    with pytest.raises(MigrationError, match="does not"):
        pending([Migration(1, "a", "select 1")], {1: Migration(1, "a", "select 1").checksum, 2: "x"})


# --- integration: only when a throwaway or dev database is given explicitly -------------------
TEST_DB = config.env_value("TIMEGLOBE_TEST_DATABASE_URL")


# A plain pytest run never connects to a database: it needs the URL AND an explicit opt-in in the
# process environment (not .env), so a database is only touched when someone asks for it.
RUN_DB_TESTS = os.environ.get("TIMEGLOBE_RUN_DB_TESTS") == "1"


@pytest.mark.skipif(
    not (TEST_DB and RUN_DB_TESTS),
    reason="database test: set TIMEGLOBE_TEST_DATABASE_URL and TIMEGLOBE_RUN_DB_TESTS=1",
)
def test_migrations_apply_cleanly_and_enforce_their_constraints():
    import psycopg

    # The test database must be its own Neon branch: refuse anything equal to DATABASE_URL.
    assert TEST_DB != config.env_value("DATABASE_URL"), "test URL must not be DATABASE_URL"
    schema = f"tg_test_{uuid.uuid4().hex[:8]}"  # everything happens inside a scratch schema
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute(f"create schema {schema}")
        try:
            conn.execute(f"set search_path to {schema}")
            migrations = discover()
            assert apply_pending(conn, migrations) == [m.version for m in migrations]
            assert apply_pending(conn, migrations) == []  # idempotent

            conn.execute(
                "insert into labs values ('NIST','n','Boulder','United States of America','US',"
                "40,-105,1,null,'current')"
            )
            conn.execute("insert into offsets values ('NIST','utc',50814,0.0,null,null)")
            with pytest.raises(psycopg.errors.UniqueViolation):
                conn.execute("insert into offsets values ('NIST','utc',50814,1.0,null,null)")
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute("insert into offsets values ('NIST','weekly',50819,1.0,null,null)")
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                conn.execute("insert into offsets values ('NOPE','utc',50819,1.0,null,null)")
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute("insert into clock_counts values ('NIST','2026-11-09',3)")
            # offsets taken from a Circular T issue must point at a stored issue
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                conn.execute("insert into offsets values ('NIST','utc',50824,1.0,null,465)")
            conn.execute(
                "insert into circular_t_issues (issue, md5, listed_md5, body) "
                "values (465, repeat('a',32), repeat('b',32), 'body')"
            )
            conn.execute("insert into offsets values ('NIST','utc',50824,1.0,null,465)")
        finally:
            conn.execute(f"drop schema {schema} cascade")
