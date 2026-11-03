# 01 · Financial Document Q&A (RAG)

> Part of my AI projects portfolio → **https://tcbryan17.github.io** · See the other projects there.

Ask plain-English questions over tax and financial documents and get answers that cite the exact source page.

## Scope
- **Corpus:** public documents only, such as IRS publications (Pub 17, 501, 535, 946, Form 1040 instructions) and a few 10-Ks from SEC EDGAR. Never personal tax data.
- **Disclaimer:** shown in the UI. "Not tax or financial advice."

## Planned stack
Python · FastAPI · Postgres + pgvector · an embedding model · reranker · Claude API

## Pipeline
1. **Ingest:** parse PDFs (keeping page numbers and section headers), chunk by section with overlap
2. **Index:** embeddings in pgvector plus a BM25/full-text index
3. **Retrieve:** hybrid search, then rerank to the top 3–5 passages
4. **Answer:** the LLM answers only from the retrieved passages and returns citations `[doc, page]`, or says "I don't know"
5. **Evaluate:** 50 hand-written Q&A pairs, tracking recall@5, answer faithfulness, and citation accuracy

## API contract (used by the site)
```
POST /ask   { "question": str }
→ { "answer": str,
    "citations": [{ "doc": str, "page": int, "snippet": str }],
    "trace": [{ "step": str, "detail": str, "ms": int }] }
```
Save one real response's `trace` to `replay/sample-run.json`. The portfolio site plays it as this project's demo.

## Status
In progress
