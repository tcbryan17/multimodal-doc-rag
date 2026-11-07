# 0010. Database access, schema and hybrid search

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
The interesting retrieval logic lives in SQL: vector search, full-text search and fusing the two. The eval also needs to compare embedders without re-ingesting the corpus. Schema changes must reach every database (local, CI, and production later) in the same order.

## Options considered
**Access layer**
- **psycopg 3 with raw SQL.** The SQL is visible, which is the part worth explaining. pgvector-python registers the vector types.
- **SQLAlchemy Core** (a query builder). Composable, but adds a layer over the SQL we want to show.
- **SQLAlchemy ORM.** Rows become objects. Good for CRUD-heavy apps, but a poor fit for retrieval queries.

**Migrations**
- **Numbered `.sql` files and our own small runner** (about 40 lines, plus a `schema_migrations` table).
- **Alembic.** The industry standard, with autogeneration and downgrades. More machinery than we need without an ORM.

**Full-text ranking**
- **Built-in `tsvector` with `ts_rank_cd`.** Works on any Postgres host. Not true BM25: it doesn't weight terms by how rare they are across the corpus.
- **True BM25 via ParadeDB `pg_search`.** Corpus-aware scoring, but it needs a different image, and host support has to be checked.

**Figure storage**
- **`bytea` in Postgres.** One store, one backup.
- **Files or object storage.** Scales better and works with a CDN, but it's another service to set up and secure.

## Decision
- **psycopg 3, raw SQL** in a small repository module. Sync connections from a small pool.
- **Migrations** are numbered `migrations/NNNN_*.sql` files applied by our own runner. Migration 0001 runs `CREATE EXTENSION IF NOT EXISTS vector`, so any host gets it, not only the Docker init script.
- **Schema:**
  - `documents`: corpus, title, company and fiscal year (10-Ks), source URL, file hash, page count. One row per source file; each handbook chapter PDF is its own document.
  - `chunks`: document, kind (text/table/figure), section path, `page_idx_start/end` (integers, for comparisons), `page_label_start/end` (text, for display), content, context header, `informational`, and a generated `tsvector` column.
  - `embeddings`: `(chunk_id, model, vector)`, with **one HNSW index per model**, built on a cast to that model's dimension and filtered to that model's rows.
  - `figures`: `(chunk_id, png bytea)`.
  - `ingest_failures`: what failed, where and why.
- **Hybrid search:** a vector query and a full-text query each return their top candidates. **Reciprocal Rank Fusion** combines them: each chunk scores `1/(60 + rank)` in each list, and the scores are summed. The reranker then takes the top ~30.
- **Full-text:** built-in `tsvector` + `ts_rank_cd`. The README's "BM25-style" becomes "keyword full-text search".
- **Figures:** `bytea` in Postgres, about 500 figures at roughly 100KB each (~50MB in total).

## Why
- **Raw SQL** keeps the retrieval queries, the part an interviewer will ask about, in plain sight.
- **Embeddings keyed by model** let 1,024- and 1,536-dimension vectors sit side by side, so the eval switches embedder with one setting. This pattern comes from the pgvector docs.
- **RRF** works on ranks, so it doesn't matter that vector distances and text-rank scores are on incomparable scales. It's standard and needs no tuning.
- **Full-text search:** fusing by rank makes `ts_rank_cd`'s scoring quirks matter less, and the built-in search keeps every host option open.

## Consequences
- Our runner has no automatic downgrades. Undoing a change means writing a new migration.
- The read-only `/ask` role (for the live demo) covers the figures too.
- Revisit `pg_search` if the eval shows that keyword retrieval is the weak link.
