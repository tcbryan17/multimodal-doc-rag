"""The read-only role (docker/roles/readonly_role.sql, control C31) can read and nothing else.

Needs Postgres and the `psql` client (the script uses psql meta-commands), so the tests are
marked `db` and skip when either is missing. Roles are server-wide, so the test uses a
unique throwaway role name and drops it afterwards.
"""

import secrets
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors, sql
from psycopg.conninfo import make_conninfo

pytestmark = pytest.mark.db

SCRIPT = Path(__file__).resolve().parent.parent / "docker" / "roles" / "readonly_role.sql"
Conn = psycopg.Connection[Any]


@pytest.fixture(scope="module")
def readonly_url(test_database_url: str) -> Iterator[str]:
    """Run the real script against the test DB; yield a URL that logs in as the new role."""
    psql = shutil.which("psql")
    if psql is None:
        pytest.skip("psql client not installed")
    role = f"rag_ro_test_{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(16)
    try:
        proc = subprocess.run(
            [psql, test_database_url, "-v", f"ro_role={role}", "-v", f"ro_password={password}"]
            + ["-X", "-q", "-f", str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        # A committed row so the SELECT test proves the role sees real data.
        with psycopg.connect(test_database_url, autocommit=True) as admin:
            admin.execute(
                "INSERT INTO documents (corpus, doc_key, title, source_url, sha256, page_count)"
                " VALUES ('faa', 'ro-role-test', 'RO', 'http://x', %s, 1)",
                (f"ro-{role}",),
            )
        yield make_conninfo(test_database_url, user=role, password=password)
    finally:
        with psycopg.connect(test_database_url, autocommit=True) as admin:
            admin.execute("DELETE FROM documents WHERE doc_key = 'ro-role-test'")
            # DROP OWNED removes the role's grants (including CONNECT) so DROP ROLE succeeds.
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


def test_readonly_role_can_select_the_four_tables(readonly_url: str) -> None:
    with psycopg.connect(readonly_url) as conn:
        for table in ("documents", "chunks", "embeddings", "figures"):
            conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
        row = conn.execute("SELECT count(*) FROM documents WHERE doc_key = 'ro-role-test'")
        assert row.fetchone() == (1,)


@pytest.mark.parametrize("table", ["documents", "chunks", "embeddings", "figures"])
def test_readonly_role_cannot_insert(readonly_url: str, table: str) -> None:
    with (
        psycopg.connect(readonly_url) as conn,
        pytest.raises(errors.InsufficientPrivilege),
    ):
        conn.execute(sql.SQL("INSERT INTO {} DEFAULT VALUES").format(sql.Identifier(table)))


def test_readonly_role_cannot_update_or_delete(readonly_url: str) -> None:
    with psycopg.connect(readonly_url) as conn:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("UPDATE documents SET title = 'changed'")
        conn.rollback()
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("DELETE FROM documents")
        conn.rollback()
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("TRUNCATE chunks")


def test_readonly_role_cannot_read_other_tables_or_create_objects(readonly_url: str) -> None:
    with psycopg.connect(readonly_url) as conn:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM ingest_failures")
        conn.rollback()
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM schema_migrations")
        conn.rollback()
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("CREATE TABLE should_not_exist (id int)")


def test_script_requires_a_password(test_database_url: str) -> None:
    psql = shutil.which("psql")
    if psql is None:
        pytest.skip("psql client not installed")
    proc = subprocess.run(
        [psql, test_database_url, "-X", "-q", "-f", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode != 0
    assert "ro_password" in proc.stdout + proc.stderr
