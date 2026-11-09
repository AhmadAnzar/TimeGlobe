"""Tiny migration runner: python -m timeglobe_pipeline.migrate

Applies pipeline/migrations/NNNN_name.sql in order, each in its own transaction, and records it in
schema_migrations with a checksum. A migration that was already applied and then edited is an error:
history is append-only, a change is a new file. Connects with DATABASE_URL from the environment or
.env, and never prints it.
"""

import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from timeglobe_pipeline import config
from timeglobe_pipeline.fetch import REPO_ROOT

MIGRATIONS_DIR = REPO_ROOT / "pipeline" / "migrations"
_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

CREATE_TRACKING = """
create table if not exists schema_migrations (
    version     integer primary key,
    name        text not null,
    checksum    text not null,
    applied_at  timestamptz not null default now()
)
"""


class MigrationError(Exception):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Read the migration files; numbering must start at 1 and have no gaps or duplicates."""
    if not directory.is_dir():
        raise MigrationError(
            f"migrations folder not found: {directory} "
            "(the package must be installed with pip install -e so paths resolve inside the checkout)"
        )
    found = []
    for path in sorted(directory.iterdir()):
        match = _NAME.match(path.name)
        if not match:
            raise MigrationError(f"{path.name}: expected NNNN_name.sql")
        found.append(Migration(int(match[1]), match[2], path.read_text(encoding="utf-8")))
    versions = [m.version for m in found]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError(f"migration numbers must be 1..N without gaps, got {versions}")
    return found


def pending(migrations: list[Migration], applied: dict[int, str]) -> list[Migration]:
    """Migrations still to apply. Raises if an applied one changed or the database is ahead."""
    known = {m.version: m for m in migrations}
    for version, checksum in applied.items():
        if version not in known:
            raise MigrationError(f"database has migration {version} that this checkout does not")
        if known[version].checksum != checksum:
            raise MigrationError(f"migration {version} ({known[version].name}) was edited after it was applied")
    return [m for m in migrations if m.version not in applied]


def apply_pending(conn, migrations: list[Migration]) -> list[int]:
    """Apply what is pending on an open psycopg connection; returns the versions applied."""
    with conn.transaction():
        conn.execute(CREATE_TRACKING)
        conn.execute("select pg_advisory_xact_lock(7266311)")  # one runner at a time
        applied = {v: c for v, c in conn.execute("select version, checksum from schema_migrations")}
    done = []
    for migration in pending(migrations, applied):
        with conn.transaction():
            conn.execute(migration.sql)
            conn.execute(
                "insert into schema_migrations (version, name, checksum) values (%s, %s, %s)",
                (migration.version, migration.name, migration.checksum),
            )
        done.append(migration.version)
    return done


def main() -> int:
    import psycopg

    config.require_db_opt_in()
    config.load_env(REPO_ROOT / ".env")
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is not set (put it in .env)", file=sys.stderr)
        return 2
    migrations = discover()
    with psycopg.connect(url, autocommit=True) as conn:
        done = apply_pending(conn, migrations)
    print(f"applied {done}" if done else "up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
