-- A failed figure description can be retried later (`scripts/ingest_corpus.py --retry-failures`).
-- Rather than deleting the failure row on success we stamp it, so the history of what failed
-- and when it was fixed stays queryable. NULL = still unresolved.
ALTER TABLE ingest_failures ADD COLUMN resolved_at timestamptz;
