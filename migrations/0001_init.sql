-- Initial schema (ADR 0010).
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    corpus       text NOT NULL CHECK (corpus IN ('10k', 'faa')),
    doc_key      text NOT NULL UNIQUE,   -- short slug used in citations
    title        text NOT NULL,
    company      text,                   -- 10-Ks only
    fiscal_year  int,                    -- 10-Ks only
    source_url   text NOT NULL,
    sha256       text NOT NULL UNIQUE,
    page_count   int NOT NULL,
    ingested_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chunks (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id      bigint NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    ordinal          int NOT NULL,
    kind             text NOT NULL CHECK (kind IN ('text', 'table', 'figure')),
    section_path     text[] NOT NULL DEFAULT '{}',
    page_idx_start   int NOT NULL,       -- integers: for comparisons
    page_idx_end     int NOT NULL,
    page_label_start text,               -- text: for display (e.g. 'F-12')
    page_label_end   text,
    content          text NOT NULL,      -- what the LLM sees
    context_header   text,
    informational    boolean,            -- figures only
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(context_header, '') || ' ' || content)
    ) STORED,
    CHECK (page_idx_end >= page_idx_start)
);
CREATE INDEX chunks_document_id_idx ON chunks (document_id);
CREATE INDEX chunks_tsv_idx ON chunks USING gin (tsv);

-- One row per (chunk, embedding model). The column has no fixed dimension so models with
-- different dimensions can coexist; pgvector's documented pattern is one partial HNSW index
-- per model, built on a cast to that model's dimension.
CREATE TABLE embeddings (
    chunk_id   bigint NOT NULL REFERENCES chunks (id) ON DELETE CASCADE,
    model      text NOT NULL,
    embedding  vector NOT NULL,
    PRIMARY KEY (chunk_id, model)
);

-- IMPORTANT: a query only uses one of these indexes if it repeats the SAME cast and the
-- SAME WHERE clause, e.g.
--   SELECT chunk_id FROM embeddings
--   WHERE model = 'qwen/qwen3-embedding-8b@1024'
--   ORDER BY embedding::vector(1024) <=> $1 LIMIT 30;
-- Adding a new embedding model therefore needs a new migration with its own index.
-- The `model` key is always '<openrouter model id>@<dimensions>', so the same model at a
-- different truncation is a different key (and needs its own index).
CREATE INDEX embeddings_qwen3_8b_1024_hnsw ON embeddings
    USING hnsw ((embedding::vector(1024)) vector_cosine_ops)
    WHERE model = 'qwen/qwen3-embedding-8b@1024';
CREATE INDEX embeddings_openai_3_small_1536_hnsw ON embeddings
    USING hnsw ((embedding::vector(1536)) vector_cosine_ops)
    WHERE model = 'openai/text-embedding-3-small@1536';

CREATE TABLE figures (
    chunk_id  bigint PRIMARY KEY REFERENCES chunks (id) ON DELETE CASCADE,
    png       bytea NOT NULL,
    width     int,
    height    int
);

CREATE TABLE ingest_failures (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id  bigint REFERENCES documents (id) ON DELETE SET NULL,
    stage        text NOT NULL,
    item_ref     text,
    error        text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);
