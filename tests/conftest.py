"""Shared fixtures. `db` tests need the compose Postgres; they skip when it is unreachable."""

import importlib.util
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from pgvector.psycopg import register_vector
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from multimodal_doc_rag.config import settings
from multimodal_doc_rag.db.migrate import migrate

DEFAULT_TEST_URL = "postgresql://rag:rag-dev-only@localhost:5433/rag_test"


@pytest.fixture(autouse=True)
def _no_openrouter_key_outside_live_tests(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only `live` tests may spend money. Once a real key sits in .env, the app's `settings`
    singleton would otherwise hand it to any test that reaches a real client (e.g. an
    un-overridden `/ask`), silently making paid network calls in a normal `pytest` run."""
    if request.node.get_closest_marker("live") is None:
        monkeypatch.setattr(settings, "openrouter_api_key", None)


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    """Create `rag_test` if needed, migrate it once per session, and yield its URL."""
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_URL)
    name = conninfo_to_dict(url)["dbname"]
    admin_url = make_conninfo(url, dbname="rag")  # maintenance DB used to CREATE DATABASE
    try:
        # CREATE DATABASE cannot run inside a transaction, hence autocommit.
        with psycopg.connect(admin_url, autocommit=True, connect_timeout=2) as admin:
            exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if exists.fetchone() is None:
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(str(name))))
        with psycopg.connect(url, connect_timeout=2) as conn:
            migrate(conn)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable for db tests ({exc}); run `docker compose up -d`")
    yield url


@pytest.fixture
def db_conn(test_database_url: str) -> Iterator[psycopg.Connection[Any]]:
    """A connection inside a transaction that is always rolled back.

    Each test sees a clean database without truncating tables, and nothing a test writes
    can leak into another test. (Needs no commits in the code under test.)
    """
    with psycopg.connect(test_database_url) as conn:
        register_vector(conn)
        # Explicitly open the outer transaction. register_vector alone leaves the connection
        # IDLE, and then a `conn.transaction()` inside the code under test (corpus ingest uses
        # one per document) would be an OUTERMOST block that really commits, leaking rows
        # into other tests. With a transaction already open it becomes a SAVEPOINT.
        conn.execute("SELECT 1")
        try:
            yield conn
        finally:
            conn.rollback()


@pytest.fixture
def mini_handbook_pdf(tmp_path: Path) -> Path:
    """The synthetic handbook PDF, built at test time (no binary committed)."""
    spec = importlib.util.spec_from_file_location(
        "make_mini_handbook", Path(__file__).parent / "fixtures" / "make_mini_handbook.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "mini_handbook.pdf"
    module.build(path)
    return path
