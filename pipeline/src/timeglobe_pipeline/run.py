"""Run an ingest job: python -m timeglobe_pipeline.run {daily|weekly|monthly|snapshot} [--out DIR]

This connects to the database in DATABASE_URL and, for the three ingest jobs, to BIPM. It refuses
to start unless TIMEGLOBE_ALLOW_DB=1 is set in the environment of this one run; the workflow sets
it, nothing else does. `snapshot` reads the database only and writes the static files to --out.
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from timeglobe_pipeline import config, ingest
from timeglobe_pipeline.fetch import REPO_ROOT
from timeglobe_pipeline.http import PoliteClient
from timeglobe_pipeline.labs import load_labs
from timeglobe_pipeline.snapshot import initial_payload_gzip
from timeglobe_pipeline.store import PostgresStore


def write_files(files: dict[str, bytes], out: Path) -> None:
    for rel, body in files.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("job", choices=["daily", "weekly", "monthly", "snapshot"])
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "snapshot")
    ap.add_argument("--date", default=date.today().isoformat())
    args = ap.parse_args(argv)

    config.require_db_opt_in()
    config.load_env(REPO_ROOT / ".env")
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    import psycopg

    today = date.fromisoformat(args.date)
    labs = load_labs()
    with psycopg.connect(url, autocommit=True) as conn:
        store = PostgresStore(conn)
        if args.job == "snapshot":
            files = ingest.snapshot_files(store, labs, today.isoformat())
            write_files(files, args.out)
            print(f"wrote {len(files)} files to {args.out}; first-frame payload "
                  f"{initial_payload_gzip(files) / 1024:.0f} KB gzip")
            return 0
        with PoliteClient(
            config.user_agent(), config.ALLOWED_PREFIXES,
            forbidden_prefixes=config.FORBIDDEN_PREFIXES, cache_dir=None,
        ) as client:
            if args.job == "daily":
                result = ingest.daily(store, client, labs, today)
            elif args.job == "weekly":
                result = ingest.weekly(store, client, today)
            else:
                result = ingest.monthly(store, client, labs, today)
    print(f"{args.job}: run {result.run_id} {result.status}, {result.rows_added} rows added, "
          f"{result.rows_changed} changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
