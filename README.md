# 01 · Multimodal Document Q&A (RAG)

> Part of my AI projects portfolio → **https://tcbryan17.github.io** · See the other projects there.

Ask plain-English questions over long documents, including ones where the answer is in a chart or diagram rather than the text. Every answer cites the exact source page.

## Scope
- **Corpora:** two public collections, chosen because they're shaped differently:
  - **SEC 10-K filings** from EDGAR: dense text and financial tables, published as HTML. Apple, Microsoft and Johnson & Johnson, with Costco held out to test generalisation.
  - **FAA *Pilot's Handbook of Aeronautical Knowledge*** (FAA-H-8083-25C): a public-domain PDF of about 500 pages, with hundreds of figures (instrument diagrams, labelled drawings, performance charts that must be read to answer a question) mixed with decorative photos.
- **Question types:** fact lookup, reading a figure, and explaining a concept. When an answer comes from a figure, the figure is shown.
- **Public documents only.** Never personal data.
- **Disclaimer (shown in the UI):** "Not financial, legal, or flight-training advice."

## Planned stack
Python · FastAPI · Postgres + pgvector (Docker Compose) · psycopg 3 with raw SQL · embedding, reranking and generation models through OpenRouter, zero-data-retention endpoints only · own retrieval code, no LangChain or LlamaIndex

Each architectural choice has a decision record in [`docs/decisions/`](docs/decisions/README.md).

## Pipeline
1. **Ingest:** parse HTML and PDF while keeping printed page labels and section headers. Route each element by type: text, tables, informational figures, and decorative images. A vision model describes each informational figure.
2. **Chunk and index:** structure-aware chunks, each with a short context header, embedded into pgvector alongside a keyword full-text index.
3. **Retrieve:** hybrid search (vector + keyword, fused with Reciprocal Rank Fusion), then rerank to the top 3–5 passages.
4. **Answer:** the LLM answers only from the retrieved passages (and the figure images among them) and returns citations `[doc, page]`, or says "I don't know".
5. **Evaluate:** human-verified Q&A sets for each corpus, with a held-out split. It tracks recall@5, correctness, faithfulness, citation accuracy, abstention, and prompt-injection resistance, and compares cost against quality across models.

## API contract (used by the site)
```
POST /ask   { "question": str, "corpus"?: str, "doc"?: str }
→ { "answer": str,
    "citations": [{ "doc": str, "page": str, "page_end"?: str,
                    "snippet": str, "image_url"?: str }],
    "trace": [{ "step": str, "detail": str, "ms": int }] }
```
`page` is the printed page label (e.g. `"4-12"` in the handbook). `page_end` appears when a passage spans a page break. `image_url` appears when the cited passage is a figure; in the replay file it's an inline `data:` URI. See [ADR 0005](docs/decisions/0005-ux-and-ask-contract.md).

```
GET /figures/{chunk_id}.png   → image/png (cached for a year; 404 if that chunk has no figure)
```
`image_url` in a live response is this path, relative to the API's base URL. A figure's image never changes after ingestion, and chunk ids are never reused, so the response is safe to cache indefinitely.
Save one real response's `trace` to `replay/sample-run.json`. The portfolio site plays it as this project's demo. A rate-limited live endpoint will follow once the eval results are good.

## Development
Needs [uv](https://docs.astral.sh/uv/) and a Docker runtime (I use [OrbStack](https://orbstack.dev)).
```bash
cp .env.example .env
docker compose up -d --wait   # Postgres + pgvector on localhost:5433
uv sync
uv run pytest
uv run uvicorn multimodal_doc_rag.api:app --reload
```

Building the index (needs `OPENROUTER_API_KEY` in `.env`; every run has a spending cap):
```bash
uv run python scripts/fetch_corpus.py                      # public 10-Ks + FAA handbook into data/
uv run python scripts/ingest_corpus.py --dry-run           # parse + cost estimate, no model calls
uv run python scripts/ingest_corpus.py --preflight-only    # ~1 cent check of the live model APIs
uv run python scripts/ingest_corpus.py                     # ingest; report in reports/ingest/
```
Evals (gold set, metrics, LLM judge, injection tests) are described in [`evals/README.md`](evals/README.md).

## Status
In progress: the pipeline, parsers, ingest and eval tooling are built and tested; real ingest and the first eval run come next.
