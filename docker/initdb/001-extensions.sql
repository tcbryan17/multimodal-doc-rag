-- Migrations (migrations/*.sql) now own the schema. This file only pre-enables the
-- extension for the local container; migration 0001 also does it so any host works.
-- Runs once, when the database volume is first created.
-- pgvector ships in the image but must be enabled per database.
CREATE EXTENSION IF NOT EXISTS vector;
