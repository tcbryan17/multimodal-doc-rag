# 0009. Models and privacy: strict zero data retention

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
0002 routes every model call through OpenRouter and defers the choice of models. The requirement is **very cheap, and no training on or retention of inputs**. The owner is wary of free endpoints that collect data.

All facts below come from OpenRouter's public catalogue (`/api/v1/embeddings/models` and `/api/v1/endpoints/zdr`), **checked 2026-11-07**. Prices change, so re-check them before relying on these numbers.

**Privacy levers.** OpenRouter offers two settings:
- An account setting that allows only zero-data-retention (ZDR) endpoints.
- Per-request fields: `provider.zdr: true` routes only to ZDR endpoints; `provider.data_collection: "deny"` excludes endpoints that may train on or store data.

Retention and training are separate axes: an endpoint can decline to train on inputs and still keep them. Some Google endpoints are flagged `safety_retention`. They keep inputs briefly for abuse checks, so they are not strict ZDR.

**What the catalogue showed**
- **No ZDR endpoint:** the free NVIDIA Nemotron embedders (including the vision-language one), Cohere embed-5, all Voyage models (including multimodal), and text-embedding-ada-002.
- **ZDR text embedders:**

  | Model | Price ($/M tokens) | Provider |
  |---|---|---|
  | qwen3-embedding-8b | 0.01 | DeepInfra, Nebius |
  | text-embedding-3-small | 0.02 | Azure |
  | bge-m3 | 0.01 | |
  | pplx-embed-v1-0.6b | 0.004 | |

  The whole corpus is about 1M tokens, so embedding costs cents and price barely matters.
- **ZDR multimodal embedders:** only gemini-embedding-2 (`safety_retention`) and titan-embed-image-v1 (128-token context).
- **ZDR rerankers:** only qwen3-reranker-8b, on a single provider (Fireworks). Its price showed as "0", which most likely means unlisted, not free. **Verify before relying on it.**
- **Cheap ZDR vision chat models:** Claude Haiku 5.5 (~$0.10 in / $0.50 out per M), Gemma 4 26B (~$0.04/$0.13), Qwen3.6-35B-A3B (~$0.01/$0.09), gpt-5-nano, Nemotron 3.5 Super VL.

## Options considered
**Privacy**
- **Strict ZDR only.**
- **Allow Google `safety_retention`.** Unlocks Gemini Embedding 2 for direct image embedding, at the cost of short-term retention.
- **No training, retention allowed.** Many more models, but providers may keep inputs.

**Embedder:** qwen3-embedding-8b, text-embedding-3-small, bge-m3.

**Reranker:** qwen3-reranker-8b with a fallback, an LLM as reranker, or no reranker in v1.

**Generation and vision:** one capable model, the cheapest open model, or an eval comparison across three.

## Decision
- **Strict ZDR only,** enforced in two layers: the account setting, **and** our client sends `provider: {zdr: true, data_collection: "deny"}` on every request, which a test verifies. Neither a misconfigured account nor a code mistake can leak data on its own.
- **Embedder:** `qwen/qwen3-embedding-8b`, truncated to **1,024 dimensions** and re-normalised. The eval baseline is `openai/text-embedding-3-small` (1,536 dimensions).
- **Reranker:** `qwen/qwen3-reranker-8b`. If it fails, we keep the hybrid-search order and record "rerank skipped" in the trace. The eval measures recall@5 with and without reranking.
- **Generation and vision:** the eval compares `anthropic/claude-haiku-5.5`, `google/gemma-4-26b-a4b-it` and `qwen/qwen3.6-35b-a3b`. Haiku is the default until results come in. The same model writes figure descriptions at indexing time and answers questions.
- **Model IDs live in config,** never in code.

## Why
- **Two privacy layers:** each one covers a failure of the other.
- **Truncating to 1,024 dimensions:** pgvector's HNSW index supports at most 2,000 dimensions for `vector`. Qwen3 embeddings are trained with Matryoshka representation learning, which packs the most important information into the first dimensions, so truncating loses little quality. Truncated vectors must be re-normalised so cosine similarity still works.
- **The reranker fallback:** the only private reranker sits on a single provider, so an outage must degrade quality rather than break `/ask`.
- **Comparing three generators:** this produces the cost-vs-quality comparison that 0002 set out to make cheap.

## Consequences
- Direct image embedding is out (see 0008).
- The UI disclaimer still notes that questions are sent to third-party model providers, even though they don't retain them.
- Revisit if a ZDR multimodal embedder or a second ZDR reranker provider appears, or if prices move materially.
