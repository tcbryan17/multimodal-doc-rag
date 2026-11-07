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
uv run pytest           # tests (DeprecationWarning is already an error via pyproject; live tests skipped)
uv run pytest -m live   # live tests: real OpenRouter calls that cost money, never run by default
uv run pre-commit install   # one-time: run lint/format/mypy/tests automatically before each commit
uv run pytest tests/test_api.py::test_health    # a single test
uv run mypy src tests   # type check (strict)
uv run ruff check .     # lint
uv run ruff format .    # format
uv run uvicorn multimodal_doc_rag.api:app --reload   # dev server
```
Before calling work done, run pytest, mypy, and ruff check. All of them pass right now.

## Conventions
- Python 3.12, managed by `uv`. Src layout: code lives in `src/multimodal_doc_rag/`.
- Secrets go in `.env` (gitignored). Keep `.env.example` up to date when adding config.
- Downloaded source documents go in `data/` (gitignored). Fetch them with a script and never commit them. Public documents only; never personal data.
- Use `httpx2`, not `httpx`, for HTTP. Starlette's TestClient deprecated `httpx`, and httpx2 is its drop-in successor from Pydantic. Model calls go through our own thin client, not a provider SDK (see ADR 0002).
- Settings live in `config.py` (pydantic-settings) as a module-level `settings` singleton. Secrets are `SecretStr` so they never show up in logs; call `.get_secret_value()` only at the point of use. `openrouter_api_key` is optional so tests and `/health` run without it, which means model-calling code must fail fast when it's `None`.
- mypy runs in strict mode. `filterwarnings = ["error::DeprecationWarning"]` in `pyproject.toml` keeps deprecations at zero. Tests marked `db` need Postgres (skipped when unreachable); tests marked `live` call OpenRouter and only run with `-m live`. CI runs everything except `live`.
- The `/ask` response shape in `README.md` is a contract with the portfolio site, which replays `replay/sample-run.json`. Don't change the shape without updating both.

## Environment notes
- Postgres 18 + pgvector 0.8.7 runs in Docker (OrbStack) on **localhost:5433**, bound to 127.0.0.1 only. Port 5433 avoids a Homebrew Postgres on 5432. Credentials are local-dev defaults from `.env`.
- `docker/initdb/*.sql` runs only when the `pgdata` volume is first created. To re-run it, wipe the volume with `docker compose down -v` (this deletes all data).
- Postgres 18 images mount data at `/var/lib/postgresql`, not `/var/lib/postgresql/data`.
- If the repo folder is moved or renamed, `.venv` breaks because it stores absolute paths. Delete `.venv` and run `uv sync`.

## Current status (update as things change)
**Done:** environment only. That covers the uv project, a FastAPI app with just `/health` and one test, config, the Docker Postgres + pgvector setup (verified working), and decision records 0001–0004. **No pipeline code exists yet.**

**Decided** (details in `docs/decisions/`):
- 0001: write our own retrieval pipeline, with no LangChain or LlamaIndex.
- 0002: all model calls go through OpenRouter, using a project-only key with a low credit limit and low rate limit. *Specific models are deferred.*
- 0003: Docker Compose for local Postgres. Build against replay first, then add a capped live `/ask` demo.
- 0004: two corpora, SEC 10-Ks (HTML from EDGAR) and the FAA *Pilot's Handbook of Aeronautical Knowledge* (FAA-H-8083-25, a PDF full of figures). The repo was renamed from `fin-doc-rag`.

**Open decisions.** The owner plans to work through these deliberately. Bring each one to them; don't decide on their behalf:
1. **Parsing:** a PDF parser for the FAA handbook and an HTML path for EDGAR 10-Ks, both preserving page numbers and section headers. 10-K page numbers come from page-break markers and footers.
2. **Image handling:** caption with a vision model then embed the caption, embed the image directly with a multimodal model (e.g. NVIDIA Nemotron Embed VL), or embed page screenshots. Also how to sort informational figures from decorative photos, and how parse failures are handled. Ideally compare approaches in the eval.
3. **Database access:** raw SQL with psycopg, a query builder, or an ORM (SQLAlchemy); plus migrations and the schema (documents, chunks, vectors, full-text index).
4. **Chunking strategy.**
5. **Models** (embedding, reranker, generation, vision). Requirement: very cheap **and** no training on or retention of inputs. The owner is wary of free endpoints that collect data. Investigate OpenRouter's privacy and zero-data-retention settings. No OpenRouter key exists yet.
6. **Eval methodology:** Q&A sets per corpus (a larger primary set, a smaller generalisation set), recall@5, faithfulness, citation accuracy, an adversarial / prompt-injection set, and a cost-vs-quality comparison across models. The owner considers eval central to the portfolio story.
7. **Deployment:** the production Postgres host (Neon is the front-runner) and app hosting, plus security hardening before the live demo. That means per-IP rate limiting, input and output caps, a read-only DB role for `/ask`, and a non-root container.
8. **Corpus specifics:** which companies and years of 10-Ks, and which handbook edition.
