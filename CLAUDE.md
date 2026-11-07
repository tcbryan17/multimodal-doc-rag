# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

It's also written as context for anyone (human or AI) working in this repo.

## What this is
A multimodal RAG system that answers questions over public documents (SEC 10-Ks and the FAA *Pilot's Handbook of Aeronautical Knowledge*), including content found only in images and charts, with page-level citations. See `README.md` for scope, pipeline, and the `/ask` API contract.

**This is a portfolio project for AI engineering job applications.** The owner needs to understand and be able to defend every significant choice in an interview. Building it is only half the goal.

## How we work together
- **The owner's understanding and decisions come first.** Don't optimise for speed at the cost of their understanding.
- **Small choices: just decide.** Examples: lint rules, file names, test layout, helper functions, dependency versions. Mention what you picked in one line so nothing is hidden.
- **Architectural or significant choices: ask before acting.** Examples: databases and hosting, PDF parsing, embedding and reranker models, chunking strategy, frameworks (LangChain/LlamaIndex vs hand-rolled), eval methodology, deployment. Lay out the options and tradeoffs, give a recommendation with reasons, then let the owner choose.
- **Record each architectural decision** in `docs/decisions/` (see the template there), including the options that were rejected and why. These records count as portfolio material too. Never edit an accepted record: write a new one that supersedes it, mark the old one's status, and update the index table in `docs/decisions/README.md`.
- The owner is new to Docker: explain container concepts when they come up.
- When adding something non-obvious, explain *why* it works, not just *what* it does.

## Commands
```bash
cp .env.example .env          # first time only
docker compose up -d --wait   # start local Postgres + pgvector (needs OrbStack running)
docker compose down           # stop it (data is kept in the pgdata volume)
uv sync                 # install deps into .venv
uv run pytest -W error::DeprecationWarning      # tests (the flag is how we keep deprecations at zero)
uv run pytest tests/test_api.py::test_health    # a single test
uv run mypy src tests   # type check (strict)
uv run ruff check .     # lint
uv run ruff format .    # format
uv run uvicorn multimodal_doc_rag.api:app --reload   # dev server
```
Before calling work done, run pytest (with the flag), mypy, and ruff check. All of them pass right now.

## Conventions
- Python 3.12, managed by `uv`. Src layout: code lives in `src/multimodal_doc_rag/`.
- Secrets go in `.env` (gitignored). Keep `.env.example` up to date when adding config.
- Downloaded source documents go in `data/` (gitignored). Fetch them with a script and never commit them. Public documents only; never personal data.
- Use `httpx2`, not `httpx`, for HTTP. Starlette's TestClient deprecated `httpx`, and httpx2 is its drop-in successor from Pydantic. Model calls go through our own thin client, not a provider SDK (see ADR 0002).
- Settings live in `config.py` (pydantic-settings) as a module-level `settings` singleton. Secrets are `SecretStr` so they never show up in logs; call `.get_secret_value()` only at the point of use. `openrouter_api_key` is optional so tests and `/health` run without it, which means model-calling code must fail fast when it's `None`.
- mypy runs in strict mode. The test suite must pass with `-W error::DeprecationWarning`. That flag isn't set in `pyproject.toml`, so pass it explicitly.
- The `/ask` response shape in `README.md` is a contract with the portfolio site, which replays `replay/sample-run.json`. Don't change the shape without updating both.

## Environment notes
- Postgres 18 + pgvector 0.8.7 runs in Docker (OrbStack) on **localhost:5433**, bound to 127.0.0.1 only. Port 5433 avoids a Homebrew Postgres on 5432. Credentials are local-dev defaults from `.env`.
- `docker/initdb/*.sql` runs only when the `pgdata` volume is first created. To re-run it, wipe the volume with `docker compose down -v` (this deletes all data).
- Postgres 18 images mount data at `/var/lib/postgresql`, not `/var/lib/postgresql/data`.
- If the repo folder is moved or renamed, `.venv` breaks because it stores absolute paths. Delete `.venv` and run `uv sync`.

## Current status (update as things change)
**Done:** the environment (uv project, FastAPI with only `/health`, config, Docker Postgres + pgvector) and decision records 0001–0013. **No pipeline code exists yet.**

**Decided** (read the ADR before working in its area; details and rejected options are in `docs/decisions/`):
- 0001: our own retrieval pipeline, with no LangChain or LlamaIndex.
- 0002: all model calls go through OpenRouter with a capped, project-only key.
- 0003: Docker Compose locally. Build against replay first, then a capped live `/ask`.
- 0004 / 0013: SEC 10-Ks (Apple, Microsoft, J&J; Costco held out) and FAA-H-8083-25C (all chapters; ~3 held out).
- 0005: v1 handles fact, figure and concept questions; figure answers show the figure; everything is searched by default with an optional filter. **Citations use printed page labels (`page: str`).**
- 0006: EDGAR HTML is parsed by hand with BeautifulSoup. **The FAA PDF parser (PyMuPDF vs Docling) is pending a spike.**
- 0007: structure-aware chunks that may span pages, a deterministic context header, and a size tuned by the eval.
- 0008: a vision-model description makes each figure findable; the image itself goes to the generator when answering; decorative images are filtered; failures degrade and are reported.
- 0009: **strict zero-data-retention.** Every OpenRouter request must send `provider: {zdr: true, data_collection: "deny"}`. qwen3-embedding-8b @1024 dims, qwen3-reranker-8b with a fallback, and Claude Haiku 5.5 as the default generator. No OpenRouter key exists yet.
- 0010: psycopg 3 with raw SQL; numbered SQL migrations; an `embeddings` table keyed by model; RRF hybrid search; figures stored as `bytea`.
- 0011: evals run outside pytest; 60 dev + 20 held-out questions per corpus; an LLM judge calibrated against human grades; injection sets.
- 0012: a walking skeleton; contract tests over fake and real implementations; db tests in a rolled-back transaction; GitHub Actions + pre-commit.

**Build plan:** `docs/build-plan.md` lists the ordered, test-first steps. Tick each one off as it lands. Next up: the FAA parser spike (0b), then the quality gate (step 1).

**Still open:** deployment (production Postgres host, app hosting, hardening: per-IP rate limits, input and output caps, a read-only DB role, a non-root container). This is deliberately deferred until after the eval, and it's the owner's decision.
