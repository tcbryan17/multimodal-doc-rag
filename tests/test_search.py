from typing import Any

import psycopg
import pytest
from psycopg import sql

from multimodal_doc_rag.fakes import HashingEmbedder
from multimodal_doc_rag.search import (
    fetch_passages,
    hybrid_search,
    keyword_search,
    vector_search,
    vector_search_query,
)

pytestmark = pytest.mark.db

Conn = psycopg.Connection[Any]
EMB = HashingEmbedder(64)

# doc_key -> (corpus, title, [(content, page_idx, page_label)])
DOCS = {
    "acme-10k": (
        "10k",
        "Acme Corp 10-K",
        [
            ("Item 1A Risk Factors describe supply chain disruption", 3, "4"),
            ("Revenue grew because of strong cloud subscription demand", 10, "11"),
            ("Item 7 liquidity and capital resources discuss cash flow", 20, "21"),
        ],
    ),
    "faa-handbook": (
        "faa",
        "FAA Pilot's Handbook",
        [
            ("The VNE never exceed speed is marked by a red line", 30, "8-5"),
            ("Airspeed indicator colour arcs show the green arc normal range", 31, "8-6"),
            ("Stall occurs when the critical angle of attack is exceeded", 40, "5-2"),
        ],
    ),
}


def _insert(conn: Conn) -> dict[str, int]:
    """Plain-SQL fixtures (no repository). Returns content -> chunk id."""
    ids: dict[str, int] = {}
    for n, (key, (corpus, title, chunks)) in enumerate(DOCS.items()):
        doc = conn.execute(
            "INSERT INTO documents (corpus, doc_key, title, source_url, sha256, page_count)"
            " VALUES (%s, %s, %s, 'http://x', %s, 100) RETURNING id",
            (corpus, key, title, f"sha{n}"),
        ).fetchone()
        assert doc is not None
        for ordinal, (content, idx, label) in enumerate(chunks):
            row = conn.execute(
                "INSERT INTO chunks (document_id, ordinal, kind, page_idx_start, page_idx_end,"
                " page_label_start, page_label_end, content, context_header)"
                " VALUES (%s, %s, 'text', %s, %s, %s, %s, %s, %s) RETURNING id",
                (doc[0], ordinal, idx, idx, label, label, content, title),
            ).fetchone()
            assert row is not None
            ids[content] = row[0]
            vec = EMB.embed_documents([f"{title}\n\n{content}"])[0]
            conn.execute(
                "INSERT INTO embeddings (chunk_id, model, embedding) VALUES (%s, %s, %s::vector)",
                (row[0], EMB.model_key, str(vec)),
            )
    return ids


def _id(ids: dict[str, int], prefix: str) -> int:
    return next(v for k, v in ids.items() if k.startswith(prefix))


def test_keyword_finds_rare_term(db_conn: Conn) -> None:
    ids = _insert(db_conn)
    assert keyword_search(db_conn, "VNE", limit=5) == [_id(ids, "The VNE")]
    assert keyword_search(db_conn, "Item 1A", limit=5)[0] == _id(ids, "Item 1A")


def test_keyword_empty_or_stopword_query(db_conn: Conn) -> None:
    _insert(db_conn)
    assert keyword_search(db_conn, "", limit=5) == []
    assert keyword_search(db_conn, "the of and", limit=5) == []


def test_vector_ranks_overlapping_chunk_first(db_conn: Conn) -> None:
    ids = _insert(db_conn)
    q = EMB.embed_query("critical angle of attack stall")
    got = vector_search(db_conn, q, model_key=EMB.model_key, dim=64, limit=3)
    assert got[0] == _id(ids, "Stall")
    assert len(got) == 3


def test_vector_rejects_bad_dims(db_conn: Conn) -> None:
    with pytest.raises(ValueError):
        vector_search(db_conn, [0.0] * 3, model_key="m", dim=64, limit=1)
    with pytest.raises(ValueError):
        vector_search_query(0, sql.SQL(""))


def test_filters(db_conn: Conn) -> None:
    ids = _insert(db_conn)
    q = EMB.embed_query("speed")
    ten_k = {ids[c[0]] for c in DOCS["acme-10k"][2]}
    got = vector_search(db_conn, q, model_key=EMB.model_key, dim=64, limit=10, corpus="10k")
    assert set(got) == ten_k
    got = vector_search(
        db_conn, q, model_key=EMB.model_key, dim=64, limit=10, doc_key="faa-handbook"
    )
    assert len(got) == 3 and not set(got) & ten_k
    assert keyword_search(db_conn, "VNE", limit=5, corpus="10k") == []
    assert keyword_search(db_conn, "VNE", limit=5, doc_key="faa-handbook") == [_id(ids, "The VNE")]


def test_hybrid_fuses_both_paths_and_builds_passages(db_conn: Conn) -> None:
    ids = _insert(db_conn)
    results = hybrid_search(db_conn, "VNE red line", EMB, candidates=5)
    assert results[0].chunk_id == _id(ids, "The VNE")
    got = [p.chunk_id for p in results]
    assert len(got) == len(set(got)) == 5
    scores = [p.score for p in results]
    assert scores == sorted(scores, reverse=True)
    top = results[0]
    assert top.doc_key == "faa-handbook"
    assert top.doc_title == "FAA Pilot's Handbook"
    assert top.page_start.idx == 30 and top.page_start.label == "8-5"
    # Vector search returns every chunk, keyword only the matching one: hits found by only
    # one path survive fusion.
    keyword_hits = set(keyword_search(db_conn, "VNE red line", limit=5))
    assert any(p.chunk_id not in keyword_hits for p in results)


def test_hybrid_keyword_only_hit_survives(db_conn: Conn) -> None:
    ids = _insert(db_conn)
    # candidates=1 limits the vector path to its single nearest chunk; the keyword path
    # contributes a different one, so both appear after fusion keeping top 2.
    results = hybrid_search(db_conn, "Item 1A", EMB, candidates=2)
    assert _id(ids, "Item 1A") in [p.chunk_id for p in results]


def test_hybrid_corpus_filter(db_conn: Conn) -> None:
    _insert(db_conn)
    results = hybrid_search(db_conn, "speed risk", EMB, corpus="10k")
    assert results and {p.doc_key for p in results} == {"acme-10k"}


def test_no_matches_returns_empty(db_conn: Conn) -> None:
    # Nothing stored, so neither path finds anything.
    assert hybrid_search(db_conn, "zzzqqq", EMB) == []


def test_fetch_passages_preserves_order(db_conn: Conn) -> None:
    ids = _insert(db_conn)
    order = [(_id(ids, "Stall"), 0.5), (_id(ids, "Item 1A"), 0.4), (_id(ids, "The VNE"), 0.1)]
    ps = fetch_passages(db_conn, order)
    assert [p.chunk_id for p in ps] == [c for c, _ in order]
    assert [p.page_start.label for p in ps] == ["5-2", "4", "8-5"]
    assert [p.score for p in ps] == [0.5, 0.4, 0.1]
    assert fetch_passages(db_conn, []) == []


def test_real_model_key_uses_hnsw_index(db_conn: Conn) -> None:
    key = "qwen/qwen3-embedding-8b@1024"
    doc = db_conn.execute(
        "INSERT INTO documents (corpus, doc_key, title, source_url, sha256, page_count)"
        " VALUES ('faa', 'idx-doc', 't', 'u', 'idxsha', 1) RETURNING id"
    ).fetchone()
    assert doc is not None
    for i in range(20):
        c = db_conn.execute(
            "INSERT INTO chunks (document_id, ordinal, kind, page_idx_start, page_idx_end,"
            " content) VALUES (%s, %s, 'text', 0, 0, 'x') RETURNING id",
            (doc[0], i),
        ).fetchone()
        assert c is not None
        v = [0.0] * 1024
        v[i] = 1.0
        db_conn.execute(
            "INSERT INTO embeddings (chunk_id, model, embedding) VALUES (%s, %s, %s::vector)",
            (c[0], key, str(v)),
        )
    # Tiny table: the planner would (rightly) pick a seq scan, so forbid it. We do not
    # ANALYZE: with real statistics on 20 rows the primary-key path looks cheaper than HNSW.
    db_conn.execute("SET LOCAL enable_seqscan = off")
    q = "[" + ",".join(["0.5"] * 1024) + "]"
    stmt = sql.SQL("EXPLAIN ") + vector_search_query(1024, sql.SQL(""))
    plan = "\n".join(r[0] for r in db_conn.execute(stmt, [q, key, q, 5]).fetchall())
    assert "embeddings_qwen3_8b_1024_hnsw" in plan, plan
    # And the real function runs end to end against that index.
    qv = [0.0] * 1024
    qv[3] = 1.0
    assert len(vector_search(db_conn, qv, model_key=key, dim=1024, limit=5)) == 5
