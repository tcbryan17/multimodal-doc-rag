"""Migration runner and schema tests (all need Postgres, so marked `db`)."""

from typing import Any

import psycopg
import pytest
from psycopg import errors

from multimodal_doc_rag.db.migrate import migrate

pytestmark = pytest.mark.db

Conn = psycopg.Connection[Any]


def _insert_doc(conn: Conn) -> int:
    row = conn.execute(
        "INSERT INTO documents (corpus, doc_key, title, source_url, sha256, page_count)"
        " VALUES ('faa', 'test-doc', 'Test', 'http://x', 'abc', 3) RETURNING id"
    ).fetchone()
    assert row is not None
    return int(row[0])


def _insert_chunk(conn: Conn, doc_id: int, content: str = "hello world", **kw: Any) -> int:
    start, end = kw.get("start", 1), kw.get("end", 1)
    row = conn.execute(
        "INSERT INTO chunks (document_id, ordinal, kind, page_idx_start, page_idx_end, content,"
        " context_header) VALUES (%s, 0, 'text', %s, %s, %s, 'Chapter 1') RETURNING id",
        (doc_id, start, end, content),
    ).fetchone()
    assert row is not None
    return int(row[0])


def test_migrating_twice_is_a_noop(test_database_url: str) -> None:
    with psycopg.connect(test_database_url) as conn:
        before = conn.execute("SELECT version, applied_at FROM schema_migrations").fetchall()
        assert migrate(conn) == []
        after = conn.execute("SELECT version, applied_at FROM schema_migrations").fetchall()
    assert before == after
    assert ("0001_init",) in [(r[0],) for r in before]


def test_tables_and_indexes_exist(db_conn: Conn) -> None:
    tables = {
        r[0] for r in db_conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    }
    assert {"documents", "chunks", "embeddings", "figures", "ingest_failures"} <= tables
    indexes = {r[0] for r in db_conn.execute("SELECT indexname FROM pg_indexes")}
    assert {"chunks_tsv_idx", "chunks_document_id_idx"} <= indexes
    assert {"embeddings_qwen3_8b_1024_hnsw", "embeddings_openai_3_small_1536_hnsw"} <= indexes


def test_tsv_is_generated_on_insert(db_conn: Conn) -> None:
    chunk_id = _insert_chunk(db_conn, _insert_doc(db_conn), "Pilots monitor altitude")
    row = db_conn.execute(
        "SELECT tsv @@ to_tsquery('english', 'altitude & chapter') FROM chunks WHERE id = %s",
        (chunk_id,),
    ).fetchone()
    assert row == (True,)  # matches both content and context_header, stemmed


def test_1024_dim_vector_round_trips(db_conn: Conn) -> None:
    import numpy as np

    chunk_id = _insert_chunk(db_conn, _insert_doc(db_conn))
    vec = np.arange(1024, dtype=np.float32) / 1024
    db_conn.execute(
        "INSERT INTO embeddings (chunk_id, model, embedding) VALUES (%s, %s, %s)",
        (chunk_id, "qwen/qwen3-embedding-8b@1024", vec),
    )
    row = db_conn.execute("SELECT embedding FROM embeddings WHERE chunk_id = %s", (chunk_id,))
    got = row.fetchone()
    assert got is not None
    assert np.allclose(got[0].to_numpy(), vec)


def test_cast_plus_where_uses_hnsw_index(db_conn: Conn) -> None:
    import numpy as np

    vec = np.zeros(1024, dtype=np.float32)
    db_conn.execute("SET LOCAL enable_seqscan = off")
    plan = db_conn.execute(
        "EXPLAIN SELECT chunk_id FROM embeddings"
        " WHERE model = 'qwen/qwen3-embedding-8b@1024'"
        " ORDER BY embedding::vector(1024) <=> %s LIMIT 5",
        (vec,),
    ).fetchall()
    assert "embeddings_qwen3_8b_1024_hnsw" in "\n".join(r[0] for r in plan)


def test_page_idx_check_rejects_backwards_range(db_conn: Conn) -> None:
    doc_id = _insert_doc(db_conn)
    with pytest.raises(errors.CheckViolation):
        _insert_chunk(db_conn, doc_id, start=5, end=4)


def test_deleting_document_cascades(db_conn: Conn) -> None:
    doc_id = _insert_doc(db_conn)
    chunk_id = _insert_chunk(db_conn, doc_id)
    db_conn.execute(
        "INSERT INTO embeddings (chunk_id, model, embedding) VALUES (%s, 'm', '[1,2,3]')",
        (chunk_id,),
    )
    db_conn.execute("INSERT INTO figures (chunk_id, png) VALUES (%s, %s)", (chunk_id, b"png"))
    db_conn.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
    for table in ("chunks", "embeddings", "figures"):
        row = db_conn.execute(f"SELECT count(*) FROM {table}").fetchone()
        assert row == (0,), table
