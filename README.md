# 01 · Multimodal Document Q&A (RAG)

> Part of my AI projects portfolio → **https://tcbryan17.github.io** · See the other projects there.

Ask plain-English questions over long documents, including ones where the answer is in a chart or diagram rather than the text. Every answer cites the exact source page.

## Scope
- **Corpora:** two public collections, chosen because they're shaped differently:
  - **SEC 10-K filings** from EDGAR: dense text and financial tables, published as HTML.
  - **FAA *Pilot's Handbook of Aeronautical Knowledge***: a public-domain PDF of about 500 pages, with hundreds of figures (instrument diagrams, labelled drawings, performance charts that must be read to answer a question) mixed with decorative photos.
- **Public documents only.** Never personal data.
- **Disclaimer (shown in the UI):** "Not financial, legal, or flight-training advice."

## Planned stack
Python · FastAPI · Postgres + pgvector (Docker Compose) · embedding, reranking and generation models through OpenRouter · own retrieval code, no LangChain or LlamaIndex

Each architectural choice has a decision record in [`docs/decisions/`](docs/decisions/README.md).

## Pipeline
1. **Ingest:** parse HTML and PDF while keeping page numbers and section headers. Route each element by type: text, tables, informational images, and decorative images.
2. **Index:** embeddings in pgvector plus a full-text (BM25-style) index.
3. **Retrieve:** hybrid search, then rerank to the top 3–5 passages.
4. **Answer:** the LLM answers only from the retrieved passages and returns citations `[doc, page]`, or says "I don't know".
5. **Evaluate:** hand-written Q&A sets for each corpus, tracking recall@5, answer faithfulness, citation accuracy, and a set of adversarial (prompt-injection) questions.

## API contract (used by the site)
```
POST /ask   { "question": str }
→ { "answer": str,
    "citations": [{ "doc": str, "page": int, "snippet": str }],
    "trace": [{ "step": str, "detail": str, "ms": int }] }
```
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

## Status
In progress
