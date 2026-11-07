"""ingest_document: figures are described, and a failed description degrades (ADR 0008)."""

from pathlib import Path
from typing import Any

import psycopg
import pytest

from multimodal_doc_rag.fakes import CaptionFigureDescriber, HashingEmbedder
from multimodal_doc_rag.ingest import ingest_document
from multimodal_doc_rag.types import (
    Corpus,
    Element,
    Figure,
    FigureDescription,
    PageRef,
    ParsedDocument,
    SourceInfo,
)

pytestmark = pytest.mark.db

Conn = psycopg.Connection[Any]
SOURCE = SourceInfo("doc-a", Corpus.FAA, "Doc A", "file://a")


def _figure(number: str, caption: str) -> Figure:
    return Figure(number=number, caption=caption, png=b"png-" + number.encode(), width=2, height=2)


class FakeParser:
    def parse(self, path: Path, source: SourceInfo) -> ParsedDocument:
        page = PageRef(0, "1")
        chart = "Figure 1-1. A chart"
        photo = "Figure 1-2. A photo"
        els = (
            Element("text", "Some intro text.", page, ("Ch 1",)),
            Element("figure", chart, page, ("Ch 1",), _figure("1-1", chart)),
            Element("figure", photo, page, ("Ch 1",), _figure("1-2", photo)),
        )
        return ParsedDocument(source, "sha-1", 1, els)


class ScriptedDescriber:
    """Informational for the chart (1-1), decorative for the photo; or raises if `boom`."""

    def __init__(self, boom: bool = False) -> None:
        self.boom = boom
        self.calls: list[tuple[bytes, str, str]] = []

    def describe(self, png: bytes, caption: str, context: str) -> FigureDescription:
        self.calls.append((png, caption, context))
        if self.boom:
            raise RuntimeError("vision model down")
        if "1-1" in caption:
            return FigureDescription(True, "A bar chart of X")
        return FigureDescription(False, "")


def _rows(conn: Conn) -> dict[str, tuple[str, bool | None]]:
    cur = conn.execute("SELECT kind, content, informational FROM chunks ORDER BY ordinal")
    return {r[1]: (r[0], r[2]) for r in cur.fetchall()}


def test_informational_and_decorative_paths(db_conn: Conn) -> None:
    describer = ScriptedDescriber()
    doc_id = ingest_document(
        db_conn, FakeParser(), Path("x"), SOURCE, embedder=HashingEmbedder(), describer=describer
    )
    assert doc_id is not None
    rows = _rows(db_conn)
    assert rows["A bar chart of X\n\nFigure 1-1. A chart"] == ("figure", True)
    assert rows["Figure 1-2. A photo"] == ("figure", False)  # decorative keeps only its caption
    assert rows["Some intro text."] == ("text", None)
    assert len(describer.calls) == 2
    assert describer.calls[0][0] == b"png-1-1"
    assert "Doc A" in describer.calls[0][2]  # context header passed as context
    assert db_conn.execute("SELECT count(*) FROM ingest_failures").fetchone() == (0,)


def test_describer_exception_degrades_and_records_failures(db_conn: Conn) -> None:
    doc_id = ingest_document(
        db_conn,
        FakeParser(),
        Path("x"),
        SOURCE,
        embedder=HashingEmbedder(),
        describer=ScriptedDescriber(boom=True),
    )
    assert doc_id is not None
    rows = _rows(db_conn)
    assert rows["Figure 1-1. A chart"] == ("figure", None)  # caption-only, undecided
    assert rows["Figure 1-2. A photo"] == ("figure", None)
    failures = db_conn.execute(
        "SELECT document_id, stage, item_ref, error FROM ingest_failures ORDER BY id"
    ).fetchall()
    assert len(failures) == 2
    assert failures[0][0] == doc_id
    assert failures[0][1] == "describe"
    assert failures[0][2].startswith("doc-a#chunk")
    assert "RuntimeError: vision model down" in failures[0][3]
    # the figure PNGs are still stored
    assert db_conn.execute("SELECT count(*) FROM figures").fetchone() == (2,)


def test_already_ingested_returns_none_without_describing(db_conn: Conn) -> None:
    first = ingest_document(
        db_conn,
        FakeParser(),
        Path("x"),
        SOURCE,
        embedder=HashingEmbedder(),
        describer=CaptionFigureDescriber(),
    )
    assert first is not None
    describer = ScriptedDescriber()
    again = ingest_document(
        db_conn, FakeParser(), Path("x"), SOURCE, embedder=HashingEmbedder(), describer=describer
    )
    assert again is None
    assert describer.calls == []
