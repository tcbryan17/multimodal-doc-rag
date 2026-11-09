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
uv run python -m multimodal_doc_rag.db.migrate   # apply SQL migrations to DATABASE_URL
uv run pytest           # tests (DeprecationWarning is already an error via pyproject; live tests skipped)
uv run pytest -m live   # live tests: real OpenRouter calls that cost money, never run by default
uv run python scripts/fetch_corpus.py           # download the corpus into data/
uv run python scripts/ingest_corpus.py --dry-run   # parse + chunk + cost estimate, no models (see --help)
uv run python scripts/run_eval.py --help        # evals; workflow in evals/README.md
uv run python scripts/embed_missing.py --dry-run   # count chunks lacking a vector for EMBEDDING_MODEL (no calls)
uv run python scripts/make_chunk_index.py --help   # chunk-size comparison database rag_chunk<N> (embeddings only)
uv run python scripts/release_check.py --help   # release gates verdict (ADR 0016); exit 0 = ready
uv run python scripts/save_replay.py --help     # record replay/sample-run.json (a real /ask, a few cents)
uv run python scripts/export_site_replay.py --site-dir ../portfolio-site   # replay -> site events + figure PNGs
uv run pre-commit install   # one-time: run lint/format/mypy/tests automatically before each commit
uv run pytest tests/test_api.py::test_health    # a single test
uv run mypy src tests scripts evals   # type check (strict)
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
**Done:** decision records 0001–0017; build-plan steps 0–14 and 16: every pipeline stage, the real ingest of both corpora, the recorded replay on the portfolio site, end-to-end `/ask` tests (text and figures), both parsers validated on the real corpus, fetch scripts; plus the step 14–16 tooling (see Build plan); pre-registered release gates and the data card (ADR 0016); the eval-validity fixes and comparison tooling (ADR 0017).

**Decided** (read the ADR before working in its area; details and rejected options are in `docs/decisions/`):
- 0001: our own retrieval pipeline, with no LangChain or LlamaIndex.
- 0002: all model calls go through OpenRouter with a capped, project-only key.
- 0003: Docker Compose locally. Build against replay first, then a capped live `/ask`.
- 0004 / 0013: SEC 10-Ks (Apple, Microsoft, J&J; Costco held out) and FAA-H-8083-25C (all chapters; ~3 held out).
- 0005: v1 handles fact, figure and concept questions; figure answers show the figure; everything is searched by default with an optional filter. **Citations use printed page labels (`page: str`).**
- 0006: EDGAR HTML is parsed by hand with BeautifulSoup; the FAA PDF uses **PyMuPDF** with our own layout rules (most figures are vector, so regions are found and rendered, not extracted).
- 0007: structure-aware chunks that may span pages, a deterministic context header, and a size tuned by the eval.
- 0008: a vision-model description makes each figure findable; the image itself goes to the generator when answering; decorative images are filtered; failures degrade and are reported.
- 0009: **strict zero-data-retention.** Every OpenRouter request must send `provider: {zdr: true, data_collection: "deny"}`. qwen3-embedding-8b @1024 dims, qwen3-reranker-8b with a fallback, and Claude Haiku 5.5 as the default generator. No OpenRouter key exists yet.
- 0010: psycopg 3 with raw SQL; numbered SQL migrations; an `embeddings` table keyed by model; RRF hybrid search; figures stored as `bytea`.
- 0011: evals run outside pytest; 60 dev + 20 held-out questions per corpus; an LLM judge calibrated against human grades; injection sets.
- 0012: a walking skeleton; contract tests over fake and real implementations; db tests in a rolled-back transaction; GitHub Actions + pre-commit.
- 0014: the eval judge is **`openai/gpt-6-luna`** (outside the Claude/Gemma/Qwen generator families, ZDR via Azure; a reasoning model, so the judge's output cap is 2,000 tokens).
- 0015: **hidden reasoning is off** for figure descriptions and `/ask` answers (`VISION_REASONING`, `GENERATION_REASONING`); output caps 3,000 / 1,200; the client records `finish_reason` so truncation is named. Eval compares generator reasoning on vs off.
- 0016: **governance**: NIST AI RMF + GenAI Profile (AI 600-1) for structure, OWASP LLM Top 10 (2026) for security controls. **Release gates are pre-registered** in `evals/gates.toml`, pinned by `tests/test_evals_gates.py`, and frozen once the dev baseline exists (a change needs a superseding ADR). The gates bind only on the held-out final run; `scripts/release_check.py` exits non-zero unless every gate passes, and missing evidence counts as "not measured", which blocks. Artifacts live in `docs/governance/`: the data card is done; the control matrix and risk register come alongside the eval; the system card comes after the held-out run. In the control matrix, never mark a deployment control implemented before it exists.

- 0017: **eval validity** (amends 0011 and 0016; thresholds unchanged). The judge is sent the figure images the generator saw (`PipelineRun.figures`), and `calibrate_judge.py grade` shows them to the owner. **Binding runs search every document**; `--corpus-filter` is a comparison. `gates.toml` has an `[evidence]` table of minimums (15 answerable held-out per corpus, 3 unanswerable, 25 hand grades, 12 direct and 5 reached indirect attacks), and injection runs must match the final run's models and settings. Comparison indexes live in their own databases (`rag_chunk<N>`), never in `rag`. The LLM-written-header comparison is deferred.

**Build plan:** `docs/build-plan.md` lists the ordered, test-first steps. Tick each one off as it lands. Steps 0–13 are done. The tooling for steps 14–16 is built and tested with fakes: corpus ingest (`scripts/ingest_corpus.py`), the eval harness (`src/multimodal_doc_rag/evals/`, CLIs in `scripts/`, data and workflow in `evals/`), and the replay writer (`scripts/save_replay.py`). Every model-calling run goes through a `CostMeter` cap (`models/cost.py`). The OpenRouter key is in `.env` ($5 credit limit; our $3/$2 caps trip first). Tests never use it: `tests/conftest.py` blanks it for everything except `-m live`. **Next, waiting on the owner:** the gold set (draft with `draft_gold.py`, the owner verifies every item and writes the figure questions), then judged smoke run (including the figure-only pass, `--type figure`, which confirms the judge's ZDR endpoint accepts images), eval runs and calibration, with the control matrix and risk register alongside (build plan step 17). Then the held-out run and release check (step 18), then deployment (step 19). Core types live in `types.py`, seams in `protocols.py`, fakes in `fakes.py`, contract suites in `tests/contracts/`.

**Still open:** deployment (production Postgres host, app hosting, hardening: per-IP rate limits, input and output caps, a read-only DB role, a non-root container; live-ops governance: whether and how long to log questions, monitoring, incident response; the EU AI Act Art. 50 AI notice). Deployment must run `release_check.py`. This is deliberately deferred until after the eval, and it's the owner's decision.
