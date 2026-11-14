-- Read-only database role for the API (control C31).
--
-- Why this exists: the API only ever READS the index (documents, chunks, embeddings,
-- figures). If it connects as the owner role, a bug or an injection that reached SQL could
-- change or delete data. With this role, the database itself refuses writes.
--
-- Why it is not a numbered migration: a role belongs to the whole Postgres server ("cluster"),
-- not to one database, and the migration runner (db/migrate.py) manages the app schema only.
-- So an admin runs this script by hand, once per database, after migrations.
--
-- Run it as a role that can create roles (the owner/admin of the database), connected to the
-- TARGET database. The password is supplied at run time and is never committed:
--
--   psql "$ADMIN_DATABASE_URL" \
--        -v ro_password="$(openssl rand -base64 24 | tr -d '/+=')" \
--        -f docker/roles/readonly_role.sql
--
-- (Keep the generated password in the host's secret store; it goes into the API's
-- DATABASE_URL. Optional: -v ro_role=<name> to change the role name, default rag_readonly.)
-- Safe to re-run: it creates the role if missing, then resets password and grants.
-- Caveat: the CREATE/ALTER ROLE statement contains the password, so it would appear in
-- server logs if log_statement is 'all' or 'ddl'. Leave statement logging off for this run.

\set ON_ERROR_STOP on

\if :{?ro_password}
\else
  -- ON_ERROR_STOP turns this error into a non-zero psql exit code.
  DO $$ BEGIN RAISE EXCEPTION 'pass the password with -v ro_password=...'; END $$;
\endif
\if :{?ro_role}
\else
  \set ro_role rag_readonly
\endif

-- format(%I / %L) quotes the identifier / literal safely; \gexec runs each result row as SQL.
-- NOSUPERUSER etc. are the defaults, spelled out so the intent is visible.
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
              :'ro_role')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'ro_role')
\gexec

SELECT format('ALTER ROLE %I PASSWORD %L', :'ro_role', :'ro_password')
\gexec

-- Start from nothing, then grant only what the API needs.
SELECT format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', :'ro_role') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'ro_role') \gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'ro_role') \gexec
SELECT format('GRANT SELECT ON documents, chunks, embeddings, figures TO %I', :'ro_role') \gexec
-- Deliberately NOT granted: ingest_failures, schema_migrations, and every INSERT, UPDATE,
-- DELETE, TRUNCATE and DDL right. Tables added by future migrations are also invisible to
-- this role until a line is added here.
