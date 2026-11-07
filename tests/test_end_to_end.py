"""The walking skeleton's proof.

A real 10-K-shaped HTML file goes through the real parser, chunker, indexer, hybrid search
and pipeline, and comes back out of `POST /ask` as a cited answer. Only the models are fakes
(no network, no key, no cost); everything else, including Postgres, is the real thing. If
this passes, every later step is replacing a fake with a better implementation.
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
from multimodal_doc_rag.parsing.edgar import EdgarHtmlParser
from multimodal_doc_rag.pipeline import RagPipeline
from multimodal_doc_rag.types import Corpus, SourceInfo

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).parent / "fixtures" / "mini_10k.html"
EMB = HashingEmbedder()


@pytest.fixture
def client(db_conn: psycopg.Connection[Any]) -> Iterator[TestClient]:
    source = SourceInfo(
        "example-10k-2025", Corpus.TEN_K, "Example Corp 10-K FY2025", "file://mini_10k.html"
    )
    ingest_document(
        db_conn,
        EdgarHtmlParser(),
        FIXTURE,
        source,
        embedder=EMB,
        describer=CaptionFigureDescriber(),
    )

    def build() -> Pipeline:
        return RagPipeline(
            db_conn, embedder=EMB, reranker=OverlapReranker(), generator=EchoGenerator()
        )

    # Hand the app the test's own rolled-back connection instead of a pooled one.
    app.dependency_overrides[get_db_conn] = lambda: db_conn
    app.dependency_overrides[get_pipeline] = build
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_ask_returns_cited_answer_with_printed_page_label(client: TestClient) -> None:
    # The supplier sentence is on the page printed "2" (page idx 2).
    r = client.post("/ask", json={"question": "Which component relies on a single supplier?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"].strip()
    assert body["citations"]
    top = body["citations"][0]
    assert top["doc"] == "Example Corp 10-K FY2025"
    assert "supplier" in top["snippet"]
    assert top["page"] == "2"
    assert [t["step"] for t in body["trace"]] == ["retrieve", "rerank", "figures", "generate"]


def test_financial_statements_page_uses_f_prefixed_label(client: TestClient) -> None:
    r = client.post("/ask", json={"question": "When do the financial statements begin?"})
    assert r.status_code == 200
    assert r.json()["citations"][0]["page"] == "F-1"
