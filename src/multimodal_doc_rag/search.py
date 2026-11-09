"""Hybrid search, read side (ADR 0010): vector + keyword candidates fused with RRF.

All retrieval SQL is here, in plain sight. Functions take a psycopg connection and return
chunk ids (or `Passage`s), so they are testable against a real Postgres with no model calls.
"""

from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg import sql

from multimodal_doc_rag.protocols import Embedder
from multimodal_doc_rag.types import ElementKind, PageRef, Passage

type Conn = psycopg.Connection[Any]


def rrf(rankings: Sequence[Sequence[int]], k: int = 60) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion: merge several best-first id lists into one.

    Each id scores sum(1 / (k + rank)) over the lists it appears in (rank starts at 1).
    We fuse *ranks*, not scores, because the inputs are incomparable: cosine distances live
    in [0, 2] and `ts_rank_cd` values are unbounded and depend on document length, so
    adding or normalising them would let one list dominate arbitrarily. A rank means the
    same thing in any list. A larger `k` flattens the gap between top ranks.

    Example, k=60, rankings [[7, 3], [3, 9]]:
        3 -> 1/62 + 1/61 = 0.03253 (in both lists)
        7 -> 1/61 = 0.01639, 9 -> 1/62 = 0.01613
    giving [(3, 0.03253), (7, 0.01639), (9, 0.01613)].

    Ties are broken by first appearance (list order, then position), so output is
    deterministic.
    """
    scores: dict[int, float] = {}  # dicts keep insertion order = first appearance
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    # sorted() is stable, so equal scores keep first-appearance order.
    return sorted(scores.items(), key=lambda kv: -kv[1])


def _filters(corpus: str | None, doc_key: str | None) -> tuple[sql.Composable, list[str]]:
    """Optional WHERE fragments on `documents` (alias d); values are bound, never inlined.

    Callers must join `documents d` only when the returned fragment is non-empty.
    """
    parts: list[sql.Composable] = []
    params: list[str] = []
    if corpus is not None:
        parts.append(sql.SQL(" AND d.corpus = %s"))
        params.append(corpus)
    if doc_key is not None:
        parts.append(sql.SQL(" AND d.doc_key = %s"))
        params.append(doc_key)
    return sql.SQL("").join(parts), params


def vector_search_query(dim: int, filters: sql.Composable) -> sql.Composed:
    """The vector SQL, exposed so a test can EXPLAIN exactly what runs.

    Placeholders, in order: query vector, model key, any filter values, query vector, limit.
    Unfiltered queries touch only `embeddings`, so the planner can walk the HNSW index
    directly; the chunks/documents joins are added only when a filter needs them.
    """
    if not isinstance(dim, int) or isinstance(dim, bool) or dim <= 0:
        raise ValueError(f"dim must be a positive int, got {dim!r}")
    joins = (
        sql.SQL(" JOIN chunks c ON c.id = e.chunk_id JOIN documents d ON d.id = c.document_id")
        if filters != sql.SQL("")
        else sql.SQL("")
    )
    # A cast's type modifier cannot be a bind parameter, so `dim` is spliced in as a
    # validated integer literal. The cast and `e.model = ...` must match the partial index
    # definition in the migration, or Postgres falls back to a sequential scan.
    return sql.SQL(
        """
        SELECT chunk_id FROM (
            SELECT e.chunk_id, e.embedding::vector({dim}) <=> %s::vector({dim}) AS dist
            FROM embeddings e{joins}
            WHERE e.model = %s{filters}
            ORDER BY e.embedding::vector({dim}) <=> %s::vector({dim})
            LIMIT %s
        ) nearest
        ORDER BY dist, chunk_id
        """
    ).format(dim=sql.Literal(dim), joins=joins, filters=filters)


def has_vector_index(conn: Conn, model_key: str) -> bool:
    """Is there a partial HNSW index for this embedding model key (see the migration)?

    Without one, `vector_search` still returns the right rows, by scanning every vector for
    the model. That is fine for a comparison run over a few thousand chunks, but a model that
    is going to serve `/ask` needs its own index, added in a new migration.
    """
    # The index's WHERE clause is stored as `(model = '<key>'::text)`, so look for the
    # quoted key. strpos, not LIKE: a key may contain `_` or `%`, which LIKE treats as wildcards.
    row = conn.execute(
        "SELECT 1 FROM pg_indexes WHERE tablename = 'embeddings'"
        " AND indexdef LIKE '%%USING hnsw%%' AND strpos(indexdef, %s) > 0 LIMIT 1",
        (f"'{model_key}'",),
    ).fetchone()
    return row is not None


def vector_search(
    conn: Conn,
    query_vec: Sequence[float],
    *,
    model_key: str,
    dim: int,
    limit: int,
    corpus: str | None = None,
    doc_key: str | None = None,
) -> list[int]:
    """Chunk ids nearest the query by cosine distance (`<=>`), nearest first."""
    if len(query_vec) != dim:
        raise ValueError(f"query vector has {len(query_vec)} dims, expected {dim}")
    filters, fparams = _filters(corpus, doc_key)
    # pgvector parses its text form '[0.1,0.2]'; sending text avoids depending on whether
    # the connection had register_vector() called.
    vec = "[" + ",".join(repr(float(x)) for x in query_vec) + "]"
    query = vector_search_query(dim, filters)
    with conn.cursor() as cur:
        # Trade-off: the HNSW index is partial (one model) and knows nothing about the
        # corpus/doc filters, which are applied after the index returns its nearest rows.
        # A plain scan could therefore return fewer than `limit` rows (or none) when the
        # filter is selective. pgvector 0.8 iterative scans keep walking the index until
        # enough rows survive the filters. `relaxed_order` is the faster mode; it may emit
        # slightly out-of-order rows, which the outer ORDER BY in the SQL fixes. The third
        # argument (is_local=true) is SET LOCAL: scoped to this transaction only.
        cur.execute("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true)")
        cur.execute(query, [vec, model_key, *fparams, vec, limit])
        return [row[0] for row in cur.fetchall()]


def keyword_search(
    conn: Conn,
    query: str,
    *,
    limit: int,
    corpus: str | None = None,
    doc_key: str | None = None,
) -> list[int]:
    """Chunk ids matching the query's full-text terms, best `ts_rank_cd` first.

    `websearch_to_tsquery` accepts raw user input safely (quotes, "or", -negation) and never
    raises on syntax. An empty or all-stopword query yields an empty tsquery, which matches
    nothing, so the result is [].
    """
    filters, fparams = _filters(corpus, doc_key)
    stmt = sql.SQL(
        """
        SELECT c.id
        FROM chunks c
        JOIN documents d ON d.id = c.document_id,
             websearch_to_tsquery('english', %s) q
        WHERE c.tsv @@ q{filters}
        ORDER BY ts_rank_cd(c.tsv, q) DESC, c.id
        LIMIT %s
        """
    ).format(filters=filters)
    with conn.cursor() as cur:
        cur.execute(stmt, [query, *fparams, limit])
        return [row[0] for row in cur.fetchall()]


def fetch_passages(conn: Conn, chunk_ids_with_scores: Sequence[tuple[int, float]]) -> list[Passage]:
    """Load chunk text and citation info for the ids, in the order given."""
    if not chunk_ids_with_scores:
        return []
    ids = [cid for cid, _ in chunk_ids_with_scores]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, d.doc_key, d.title, c.kind, c.page_idx_start, c.page_label_start,
                   c.page_idx_end, c.page_label_end, c.content, coalesce(c.context_header, '')
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE c.id = ANY(%s)
            """,
            (ids,),
        )
        rows = {row[0]: row for row in cur.fetchall()}  # SQL gives no order; restore it below
    passages: list[Passage] = []
    kind: ElementKind
    for cid, score in chunk_ids_with_scores:
        row = rows.get(cid)
        if row is None:
            continue  # chunk deleted between search and fetch
        kind = row[3]
        passages.append(
            Passage(
                chunk_id=cid,
                doc_key=row[1],
                doc_title=row[2],
                kind=kind,
                page_start=PageRef(row[4], row[5]),
                page_end=PageRef(row[6], row[7]),
                content=row[8],
                context_header=row[9],
                score=score,
            )
        )
    return passages


def hybrid_search(
    conn: Conn,
    query: str,
    embedder: Embedder,
    *,
    candidates: int = 30,
    corpus: str | None = None,
    doc_key: str | None = None,
) -> list[Passage]:
    """Vector + keyword search, fused with RRF; `Passage.score` is the RRF score."""
    vec_ids = vector_search(
        conn,
        embedder.embed_query(query),
        model_key=embedder.model_key,
        dim=embedder.dim,
        limit=candidates,
        corpus=corpus,
        doc_key=doc_key,
    )
    kw_ids = keyword_search(conn, query, limit=candidates, corpus=corpus, doc_key=doc_key)
    fused = rrf([vec_ids, kw_ids])[:candidates]
    return fetch_passages(conn, fused)


def fetch_figure_pngs(conn: Conn, chunk_ids: Sequence[int]) -> dict[int, bytes]:
    """PNG bytes for the given chunk ids that are figures; other ids are simply absent."""
    if not chunk_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT chunk_id, png FROM figures WHERE chunk_id = ANY(%s)", (list(chunk_ids),)
        )
        return {row[0]: bytes(row[1]) for row in cur.fetchall()}
