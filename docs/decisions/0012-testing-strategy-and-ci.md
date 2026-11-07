# 0012. Testing strategy and CI

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
The owner wants the RAG built test-first, with every commit green and problems surfacing immediately. Some things can't run in tests:
- real model calls (they need a key, cost money, and give different answers each run)
- the full corpus (too large)

## Options considered
**How to stage the build**
- **Stage by stage.** Finish parsing, then chunking, and so on. Each stage is complete before moving on, but the end-to-end path exists only at the end, so integration problems surface late.
- **A strict-xfail roadmap.** Write every test up front marked as expected to fail. The full map is visible immediately, but many tests sit idle for weeks.
- **A walking skeleton.** Get a thin end-to-end path working first, using fakes where needed, then make one piece real per commit.

**Automated checks**
- GitHub Actions only, a local hook only, or both.

**Database in tests**
- **testcontainers.** Starts a fresh container per session automatically, but adds a dependency and is slower.
- **The compose database** with a separate test database and a rollback after each test.

## Decision
- **Walking skeleton:** fixture document → parse → chunk → embed → store → search → answer → `/ask`, working early. Every commit is green.
- **Test layers:**
  1. **Unit tests** for pure logic: chunking, RRF, prompt building, citation validation, Matryoshka truncation.
  2. **Contract tests:** one suite per protocol (`Parser`, `Embedder`, `Reranker`, `Generator`, `FigureDescriber`), run against every implementation, fake and real. Swapping a fake for the real thing must pass the same suite.
  3. **Model-client tests** use `httpx2.MockTransport`, a fake network. They check that every request carries `zdr: true` and `data_collection: "deny"`, and that errors are handled.
  4. **Integration tests** run against real Postgres and pgvector, marked `db`.
  5. **API tests** use `TestClient` and check the `/ask` contract.
- **Fixtures:** small synthetic documents we write ourselves, kept in `tests/fixtures/`. Real source documents are never committed.
- **Test database:** the compose Postgres with a separate `rag_test` database, migrated once per session. Each test runs in a transaction that is rolled back afterwards. `/ask` receives its connection through dependency injection, so end-to-end tests can hand it the test's own transaction. `db` tests skip when no database is reachable.
- **CI:** GitHub Actions on every push and PR runs ruff, ruff format check, mypy and pytest, including the `db` tests against a `pgvector/pgvector:0.8.7-pg18` service container. A local `pre-commit` hook runs the fast checks through `uv run`, so mypy sees the project's dependencies, the same as in CI.
- **`DeprecationWarning` is an error,** set in pytest config.
- **`live` tests** (real OpenRouter calls) are opt-in and skipped by default.

## Why
The skeleton gives us a working RAG to poke at early, and every later change is checked against the whole path. Contract tests make "replace the fake" a verifiable step rather than an act of faith. Rolling back each test's transaction keeps tests isolated and fast without a container per test. CI makes the green status visible to reviewers.

## Consequences
- The fakes must stay trivial, so they aren't a second implementation to maintain.
- Without the database running locally, `db` tests skip, so CI is the backstop.
