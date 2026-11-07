"""Write side of the database: documents, chunks, figures, embeddings, failures (ADR 0010).

Raw SQL on purpose: the statements are the documentation.

TRANSACTION RULE: every function here takes a connection and NEVER commits. The caller owns
the transaction. That is what lets tests run inside a transaction that is rolled back, and
what lets ingestion commit one whole document (rows + chunks + figures + embeddings) as a
single atomic unit, so a crash midway leaves no half-indexed document behind.

The connection must have the pgvector adapter registered (`register_vector(conn)`), so that
`Vector` values travel as the `vector` type.
"""

from collections.abc import Sequence
from typing import Any

import psycopg
from pgvector import Vector

from multimodal_doc_rag.protocols import Embedder
from multimodal_doc_rag.types import Chunk, ParsedDocument

Conn = psycopg.Connection[Any]


def document_exists(conn: Conn, sha256: str) -> bool:
    row = conn.execute("SELECT 1 FROM documents WHERE sha256 = %s", (sha256,)).fetchone()
    return row is not None


def insert_document(conn: Conn, parsed: ParsedDocument) -> int:
    src = parsed.source
    row = conn.execute(
        "INSERT INTO documents"
        " (corpus, doc_key, title, company, fiscal_year, source_url, sha256, page_count)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            src.corpus.value,  # the CHECK constraint wants '10k'/'faa', not the enum object
            src.doc_key,
            src.title,
            src.company,
            src.fiscal_year,
            src.source_url,
            parsed.sha256,
            parsed.page_count,
        ),
    ).fetchone()
    assert row is not None  # INSERT ... RETURNING always yields a row
    return int(row[0])


def insert_chunks(conn: Conn, document_id: int, chunks: Sequence[Chunk]) -> list[int]:
    """Insert chunks (and a `figures` row for each figure chunk); ids returned in input order."""
    if not chunks:
        return []
    params = [
        (
            document_id,
            c.ordinal,
            c.kind,
            list(c.section_path),  # psycopg adapts a Python list to text[]
            c.page_start.idx,
            c.page_end.idx,
            c.page_start.label,
            c.page_end.label,
            c.content,
            c.context_header,
            c.informational,
        )
        for c in chunks
    ]
    ids: list[int] = []
    with conn.cursor() as cur:
        # returning=True keeps one result set per parameter row, in order; nextset() walks them.
        # That is what guarantees ids line up with the input, without a query per chunk.
        cur.executemany(
            "INSERT INTO chunks (document_id, ordinal, kind, section_path,"
            " page_idx_start, page_idx_end, page_label_start, page_label_end,"
            " content, context_header, informational)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            params,
            returning=True,
        )
        while True:
            row = cur.fetchone()
            assert row is not None
            ids.append(int(row[0]))
            if not cur.nextset():
                break
        figure_rows = [
            (chunk_id, c.figure.png, c.figure.width, c.figure.height)
            for chunk_id, c in zip(ids, chunks, strict=True)
            if c.figure is not None
        ]
        if figure_rows:
            cur.executemany(
                "INSERT INTO figures (chunk_id, png, width, height) VALUES (%s, %s, %s, %s)",
                figure_rows,
            )
    return ids


def insert_embeddings(
    conn: Conn,
    model_key: str,
    chunk_ids: Sequence[int],
    vectors: Sequence[Sequence[float]],
) -> None:
    if len(chunk_ids) != len(vectors):
        raise ValueError(f"got {len(chunk_ids)} chunk ids but {len(vectors)} vectors")
    if not vectors:
        return
    dim = len(vectors[0])
    if any(len(v) != dim for v in vectors):
        # The column has no fixed dimension (so models can coexist), which means Postgres
        # would happily accept a ragged batch. We must catch it here.
        raise ValueError("all vectors in a batch must have the same dimension")
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO embeddings (chunk_id, model, embedding) VALUES (%s, %s, %s)",
            [(cid, model_key, Vector(list(v))) for cid, v in zip(chunk_ids, vectors, strict=True)],
        )


def index_document(
    conn: Conn,
    parsed: ParsedDocument,
    chunks: Sequence[Chunk],
    embedder: Embedder,
    *,
    batch_size: int = 64,
) -> int | None:
    """Write one document with its chunks and embeddings. None (and no writes) if already there."""
    if document_exists(conn, parsed.sha256):
        return None
    document_id = insert_document(conn, parsed)
    chunk_ids = insert_chunks(conn, document_id, chunks)
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        vectors = embedder.embed_documents([c.embed_text for c in batch])
        insert_embeddings(conn, embedder.model_key, chunk_ids[start : start + batch_size], vectors)
    return document_id


def embed_missing(conn: Conn, embedder: Embedder, *, batch_size: int = 64) -> int:
    """Embed every chunk that has no row for this embedder's model; return how many.

    This is how a second embedding model is added without re-ingesting (ADR 0010).
    """
    total = 0
    while True:
        # Re-query each round instead of paging: embedded chunks drop out of the result, so
        # LIMIT alone walks the whole backlog and the loop ends when nothing is missing.
        rows = conn.execute(
            "SELECT c.id, coalesce(c.context_header, ''), c.content FROM chunks c"
            " WHERE NOT EXISTS ("
            "   SELECT 1 FROM embeddings e WHERE e.chunk_id = c.id AND e.model = %s)"
            " ORDER BY c.id LIMIT %s",
            (embedder.model_key, batch_size),
        ).fetchall()
        if not rows:
            return total
        # Same text as Chunk.embed_text, rebuilt from the stored columns.
        texts = [f"{header}\n\n{content}" for _, header, content in rows]
        insert_embeddings(
            conn, embedder.model_key, [r[0] for r in rows], embedder.embed_documents(texts)
        )
        total += len(rows)


def record_ingest_failure(
    conn: Conn, document_id: int | None, stage: str, item_ref: str | None, error: str
) -> None:
    conn.execute(
        "INSERT INTO ingest_failures (document_id, stage, item_ref, error) VALUES (%s, %s, %s, %s)",
        (document_id, stage, item_ref, error),
    )
