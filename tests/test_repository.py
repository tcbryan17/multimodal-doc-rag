"""Repository write-side tests. They run inside `db_conn`'s rolled-back transaction."""

import struct
import zlib
from typing import Any

import psycopg
import pytest

from multimodal_doc_rag.db import repository as repo
from multimodal_doc_rag.fakes import HashingEmbedder
from multimodal_doc_rag.types import (
    Chunk,
    Corpus,
    Element,
    Figure,
    PageRef,
    ParsedDocument,
    SourceInfo,
)

pytestmark = pytest.mark.db

Conn = psycopg.Connection[Any]


def _png() -> bytes:
    """A valid 1x1 PNG, built by hand so the test needs no image library."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


PNG = _png()
FIG = Figure(number="8-1", caption="Altimeter", png=PNG, width=1, height=1)
SHA = "a" * 64


def _parsed(sha: str = SHA, key: str = "faa-test-ch8") -> ParsedDocument:
    source = SourceInfo(
        doc_key=key,
        corpus=Corpus.FAA,
        title="Test Handbook",
        source_url="https://example.test/h.pdf",
    )
    el = Element(kind="text", text="x", page=PageRef(0, "8-1"), section_path=())
    return ParsedDocument(source=source, sha256=sha, page_count=3, elements=(el,))


def _chunks() -> list[Chunk]:
    return [
        Chunk(
            ordinal=0,
            kind="text",
            section_path=("Ch 8", "Altimeters"),
            page_start=PageRef(0, "8-1"),
            page_end=PageRef(0, "8-1"),
            content="The altimeter shows pressure altitude.",
            context_header="Handbook > Ch 8 > Altimeters",
        ),
        Chunk(  # spans a page break
            ordinal=1,
            kind="text",
            section_path=("Ch 8",),
            page_start=PageRef(1, "8-2"),
            page_end=PageRef(2, None),  # unlabelled page
            content="Airspeed indicators measure dynamic pressure.",
            context_header="Handbook > Ch 8",
        ),
        Chunk(
            ordinal=2,
            kind="figure",
            section_path=("Ch 8",),
            page_start=PageRef(2, None),
            page_end=PageRef(2, None),
            content="Diagram of an altimeter face.",
            context_header="Handbook > Ch 8 > Figure 8-1",
            figure=FIG,
            informational=True,
        ),
    ]


def _count(conn: Conn, table: str) -> int:
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()  # table is a test constant
    assert row is not None
    return int(row[0])


def test_rows_land_with_right_columns(db_conn: Conn) -> None:
    doc_id = repo.index_document(db_conn, _parsed(), _chunks(), HashingEmbedder())
    assert doc_id is not None
    doc = db_conn.execute(
        "SELECT corpus, doc_key, sha256, page_count FROM documents WHERE id = %s", (doc_id,)
    ).fetchone()
    assert doc == ("faa", "faa-test-ch8", SHA, 3)
    rows = db_conn.execute(
        "SELECT ordinal, section_path, page_idx_start, page_idx_end, page_label_start,"
        " page_label_end, tsv <> ''::tsvector FROM chunks WHERE document_id = %s ORDER BY ordinal",
        (doc_id,),
    ).fetchall()
    assert rows[0] == (0, ["Ch 8", "Altimeters"], 0, 0, "8-1", "8-1", True)
    assert rows[1] == (1, ["Ch 8"], 1, 2, "8-2", None, True)  # two pages, one unlabelled


def test_chunk_ids_returned_in_input_order(db_conn: Conn) -> None:
    doc_id = repo.insert_document(db_conn, _parsed())
    ids = repo.insert_chunks(db_conn, doc_id, _chunks())
    assert len(ids) == 3
    ordinals = [
        db_conn.execute("SELECT ordinal FROM chunks WHERE id = %s", (i,)).fetchone() for i in ids
    ]
    assert ordinals == [(0,), (1,), (2,)]


def test_figure_row_created_only_for_figure_chunks(db_conn: Conn) -> None:
    doc_id = repo.insert_document(db_conn, _parsed())
    ids = repo.insert_chunks(db_conn, doc_id, _chunks())
    assert _count(db_conn, "figures") == 1
    fig = db_conn.execute("SELECT chunk_id, png, width, height FROM figures").fetchone()
    assert fig is not None
    assert fig[0] == ids[2]
    assert bytes(fig[1]) == PNG
    assert fig[2:] == (1, 1)


def test_embeddings_stored_under_model_key_with_dimension(db_conn: Conn) -> None:
    embedder = HashingEmbedder(dim=64)
    repo.index_document(db_conn, _parsed(), _chunks(), embedder, batch_size=2)
    rows = db_conn.execute("SELECT DISTINCT model, vector_dims(embedding) FROM embeddings")
    assert rows.fetchall() == [("fake/hashing@64", 64)]
    assert _count(db_conn, "embeddings") == 3


def test_reindex_same_sha256_is_a_noop(db_conn: Conn) -> None:
    embedder = HashingEmbedder()
    assert repo.index_document(db_conn, _parsed(), _chunks(), embedder) is not None
    before = {t: _count(db_conn, t) for t in ("documents", "chunks", "embeddings", "figures")}
    assert repo.document_exists(db_conn, SHA)
    assert repo.index_document(db_conn, _parsed(), _chunks(), embedder) is None
    after = {t: _count(db_conn, t) for t in before}
    assert before == after


def test_embed_missing_fills_only_missing_rows(db_conn: Conn) -> None:
    repo.index_document(db_conn, _parsed(), _chunks(), HashingEmbedder(dim=64))
    second = HashingEmbedder(dim=32)
    assert repo.embed_missing(db_conn, second, batch_size=2) == 3  # forces two batches
    assert repo.embed_missing(db_conn, second) == 0
    assert repo.embed_missing(db_conn, HashingEmbedder(dim=64)) == 0  # first model is complete
    models = db_conn.execute(
        "SELECT model, count(*) FROM embeddings GROUP BY model ORDER BY model"
    ).fetchall()
    assert models == [("fake/hashing@32", 3), ("fake/hashing@64", 3)]


def test_insert_embeddings_rejects_bad_input(db_conn: Conn) -> None:
    with pytest.raises(ValueError, match="chunk ids"):
        repo.insert_embeddings(db_conn, "m@2", [1, 2], [[1.0, 0.0]])
    with pytest.raises(ValueError, match="same dimension"):
        repo.insert_embeddings(db_conn, "m@2", [1, 2], [[1.0, 0.0], [1.0]])


def test_record_ingest_failure_writes_a_row(db_conn: Conn) -> None:
    doc_id = repo.insert_document(db_conn, _parsed())
    repo.record_ingest_failure(db_conn, doc_id, "describe_figure", "fig 8-1", "vision timeout")
    repo.record_ingest_failure(db_conn, None, "fetch", None, "404")
    rows = db_conn.execute(
        "SELECT document_id, stage, item_ref, error FROM ingest_failures ORDER BY id"
    ).fetchall()
    assert rows == [
        (doc_id, "describe_figure", "fig 8-1", "vision timeout"),
        (None, "fetch", None, "404"),
    ]


def test_nothing_is_committed(db_conn: Conn, test_database_url: str) -> None:
    sha = "b" * 64
    repo.index_document(db_conn, _parsed(sha=sha, key="uncommitted"), _chunks(), HashingEmbedder())
    repo.record_ingest_failure(db_conn, None, "x", None, "boom")
    assert repo.document_exists(db_conn, sha)  # visible inside our own transaction
    with psycopg.connect(test_database_url) as other:  # a separate session sees only commits
        assert not repo.document_exists(other, sha)
        assert _count(other, "ingest_failures") == 0
