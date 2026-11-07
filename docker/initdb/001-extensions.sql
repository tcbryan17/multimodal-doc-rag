-- Runs once, when the database volume is first created.
-- pgvector ships in the image but must be enabled per database.
CREATE EXTENSION IF NOT EXISTS vector;
