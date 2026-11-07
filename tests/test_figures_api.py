"""`GET /figures/{chunk_id}.png`: reads the figures table only, needs no model key."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from multimodal_doc_rag.api import app, get_db_conn
from multimodal_doc_rag.config import settings
from multimodal_doc_rag.fakes import CaptionFigureDescriber, HashingEmbedder
from multimodal_doc_rag.ingest import ingest_document
from multimodal_doc_rag.parsing.handbook_pdf import HandbookPdfParser
from multimodal_doc_rag.types import Corpus, SourceInfo

pytestmark = pytest.mark.db

Conn = psycopg.Connection[Any]


@pytest.fixture
def client(
    db_conn: Conn, mini_handbook_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    ingest_document(
        db_conn,
        HandbookPdfParser(),
        mini_handbook_pdf,
        SourceInfo("mini-phak", Corpus.FAA, "Mini Handbook", "file://mini.pdf"),
        embedder=HashingEmbedder(),
        describer=CaptionFigureDescriber(),
    )
    # The endpoint must not depend on a model key: prove it by removing it.
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    app.dependency_overrides[get_db_conn] = lambda: db_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def _first(db_conn: Conn, kind: str) -> tuple[int, bytes | None]:
    row = db_conn.execute(
        "SELECT c.id, f.png FROM chunks c LEFT JOIN figures f ON f.chunk_id = c.id "
        "WHERE c.kind = %s ORDER BY c.id LIMIT 1",
        (kind,),
    ).fetchone()
    assert row is not None
    return int(row[0]), None if row[1] is None else bytes(row[1])


def test_returns_stored_png_with_immutable_cache(client: TestClient, db_conn: Conn) -> None:
    chunk_id, png = _first(db_conn, "figure")
    assert png is not None
    r = client.get(f"/figures/{chunk_id}.png")
    assert r.status_code == 200
    assert r.content == png
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_unknown_id_is_404(client: TestClient) -> None:
    assert client.get("/figures/999999999.png").status_code == 404


def test_text_chunk_id_is_404(client: TestClient, db_conn: Conn) -> None:
    text_id, png = _first(db_conn, "text")
    assert png is None
    assert client.get(f"/figures/{text_id}.png").status_code == 404


@pytest.mark.parametrize("bad", ["abc", "0", "-3", "1.5"])
def test_non_positive_int_id_is_422(client: TestClient, bad: str) -> None:
    assert client.get(f"/figures/{bad}.png").status_code == 422
