"""The multimodal end-to-end proof (ADR 0005, 0008).

A synthetic handbook PDF with real figures goes through the real PDF parser, figure
extraction, chunking, indexing, hybrid search and pipeline. `POST /ask` returns a citation
whose `image_url` the same client can fetch, and the bytes served are exactly the PNG stored
at ingest. Only the models are fakes (no network, no key).
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from multimodal_doc_rag.api import app, get_db_conn, get_pipeline
from multimodal_doc_rag.contracts import Pipeline
from multimodal_doc_rag.fakes import (
    CaptionFigureDescriber,
    EchoGenerator,
    HashingEmbedder,
    OverlapReranker,
)
from multimodal_doc_rag.ingest import ingest_document
from multimodal_doc_rag.parsing.handbook_pdf import HandbookPdfParser
from multimodal_doc_rag.pipeline import RagPipeline
from multimodal_doc_rag.types import Corpus, SourceInfo

pytestmark = pytest.mark.db

EMB = HashingEmbedder()


@pytest.fixture
def client(db_conn: psycopg.Connection[Any], mini_handbook_pdf: Path) -> Iterator[TestClient]:
    ingest_document(
        db_conn,
        HandbookPdfParser(),
        mini_handbook_pdf,
        SourceInfo("mini-phak", Corpus.FAA, "Mini Handbook", "file://mini.pdf"),
        embedder=EMB,
        describer=CaptionFigureDescriber(),
    )

    def build() -> Pipeline:
        return RagPipeline(
            db_conn, embedder=EMB, reranker=OverlapReranker(), generator=EchoGenerator()
        )

    app.dependency_overrides[get_db_conn] = lambda: db_conn
    app.dependency_overrides[get_pipeline] = build
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_figure_question_cites_a_fetchable_image_on_the_printed_page(
    client: TestClient, db_conn: psycopg.Connection[Any]
) -> None:
    r = client.post("/ask", json={"question": "Lift versus angle of attack figure"})
    assert r.status_code == 200
    cited = [c for c in r.json()["citations"] if "image_url" in c]
    assert cited, "expected a citation backed by a figure"
    citation = cited[0]
    # Figure 1-1 sits on the page whose printed footer label is "1-1".
    assert citation["page"] == "1-1"

    img = client.get(citation["image_url"])
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png"
    assert img.content.startswith(b"\x89PNG\r\n\x1a\n")
    chunk_id = int(citation["image_url"].removeprefix("/figures/").removesuffix(".png"))
    row = db_conn.execute("SELECT png FROM figures WHERE chunk_id = %s", (chunk_id,)).fetchone()
    assert row is not None
    assert img.content == bytes(row[0])
