# 5. Lexical and vector search

## What it does
There are two ways to find candidate chunks, and both live in SQL. Vector search embeds the question and finds the nearest chunk vectors by cosine distance (`<=>`), using a partial HNSW index built for one model. Keyword search uses Postgres full text: the question goes through `websearch_to_tsquery('english', ...)`, which accepts raw user input safely, and chunks are ranked by `ts_rank_cd` against a generated `tsvector` column that covers the context header and the content. Each search returns its top 30 chunk ids (the `candidates` default). Optional corpus and document filters are bound as parameters. The HNSW index knows nothing about those filters, so vector search turns on pgvector's iterative scan (`relaxed_order`) for the transaction, so a selective filter does not return too few rows.

## Where it lives
- `src/multimodal_doc_rag/search.py::vector_search`
- `src/multimodal_doc_rag/search.py::vector_search_query`
- `src/multimodal_doc_rag/search.py::keyword_search`
- `src/multimodal_doc_rag/search.py::has_vector_index`
- `src/multimodal_doc_rag/search.py::fetch_passages`
- `migrations/0001_init.sql` (`chunks.tsv`, `chunks_tsv_idx`, `embeddings_qwen3_8b_1024_hnsw`)

## What was chosen and why
ADR 0010. Raw SQL through psycopg 3 keeps the retrieval queries, the part an interviewer will ask about, in plain sight. The `embeddings` table is keyed by model, with one partial HNSW index per model, so 1,024- and 1,536-dimension vectors can sit side by side. A query only uses its index if it repeats the same cast and the same `WHERE model = ...` clause, which is why `vector_search_query` is exposed for a test to `EXPLAIN`. Full text uses the built-in `tsvector` and `ts_rank_cd`, which works on any Postgres host. It is not true BM25, because it does not weight terms by how rare they are across the corpus. The README calls it "keyword full-text search" for that reason.

## Options rejected
| Option | Why rejected | When it would win |
|---|---|---|
| SQLAlchemy Core or ORM | Adds a layer over the SQL we want to show | A CRUD-heavy app |
| True BM25 with ParadeDB `pg_search` | Needs a different image, and host support was unchecked | If the eval showed keyword retrieval is the weak link |
| Vector search only | Misses exact terms such as names, numbers and form codes | Purely conceptual questions |
| Keyword search only | Misses paraphrases | A corpus with a controlled vocabulary |
| One shared HNSW index for all models | Dimensions differ, and the index needs a fixed cast | A single-model system |

## Evidence
- `tests/` includes db tests (marked `db`) that run against a real Postgres, including an `EXPLAIN` check on the vector query.
- Not measured yet: recall@5 for vector alone, keyword alone and fused. To measure it, add a retrieval-only eval mode that scores each list on its own. Also not measured: whether `ts_rank_cd` is the weak link, which is the condition ADR 0010 names for revisiting `pg_search`.

## Interview questions
1. Why is `ts_rank_cd` not BM25, and when would that matter on this corpus?

**Your answer:**

2. Why does the vector query repeat the `::vector(1024)` cast and the `WHERE model = ...` clause? What happens if it does not?

**Your answer:**

3. A corpus filter is applied after the HNSW index returns its nearest rows. What can go wrong, and what does iterative scan do about it?

**Your answer:**

4. What kind of question does keyword search win, and what kind does vector search win? Give one example of each from the handbook or a 10-K.

**Your answer:**

5. `websearch_to_tsquery` is used for the keyword side. Why not `to_tsquery`, and what about SQL injection?

**Your answer:**
