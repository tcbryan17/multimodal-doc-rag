"""A tiny migration runner: applies migrations/NNNN_*.sql in order, once each (ADR 0010)."""

from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from multimodal_doc_rag.config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"
# Arbitrary constant naming our advisory lock. Postgres advisory locks are app-defined mutexes.
LOCK_ID = 7_265_001


def migrate(conn: psycopg.Connection[Any], directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations; return the versions applied this run (empty if none)."""
    applied_now: list[str] = []
    # Session-level lock: a second runner blocks here until the first finishes, then sees
    # the finished work and skips it. Taken outside any transaction so it spans all files.
    conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
    conn.commit()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        conn.commit()
        for path in sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql")):
            version = path.stem
            if version in done:
                continue
            # One transaction per file: the DDL and its bookkeeping row commit together,
            # so a failure leaves neither behind (Postgres DDL is transactional).
            with conn.transaction():
                conn.execute(sql.SQL(path.read_text()))
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            applied_now.append(version)
    finally:
        conn.rollback()  # clear any aborted transaction so the unlock can run
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
        conn.commit()
    return applied_now


if __name__ == "__main__":
    with psycopg.connect(settings.database_url.get_secret_value()) as connection:
        applied = migrate(connection)
    print(f"applied: {', '.join(applied) if applied else 'nothing (up to date)'}")
