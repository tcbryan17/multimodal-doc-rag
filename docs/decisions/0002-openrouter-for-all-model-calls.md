# 0002. Route all model calls through OpenRouter

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
The pipeline needs three kinds of model: an embedding model, a reranker, and a generation model (plus, probably, a vision model for image-heavy documents). The original README planned to call the Claude API directly for generation. The live demo will be public, so cost and abuse limits matter.

## Options considered
- **A direct provider API for each model** (e.g. Claude for generation, Voyage or Cohere for embeddings and reranking). Pros: no middleman, and access to provider-only features (e.g. Cohere's Context Focus isn't available through OpenRouter's rerank API). Cons: several keys, accounts and billing setups, and switching models means code changes.
- **OpenRouter for everything.** Pros: one key and one bill, including free tiers (e.g. NVIDIA Nemotron embedding models); embeddings, rerank and chat endpoints are all on one base URL; switching a model only changes a string, which makes model-comparison evals cheap to run; credit limits per key cap the cost of a public demo. Cons: an extra hop, free endpoints are rate limited and labelled "not for production", some free providers log or train on inputs, and models on the free tier can disappear.
- **Self-hosted models.** Pros: free per call, and fully private. Cons: needs a GPU or slow CPU inference, plus heavy ops work for a portfolio demo.

## Decision
All model calls go through OpenRouter with a key used only for this project, a very low credit limit, and a low rate limit. Model IDs live in config, not code. We call the HTTP endpoints directly with `httpx2` rather than a provider SDK. The rerank endpoint isn't OpenAI-compatible anyway, and this keeps one thin, visible client, in line with 0001.

## Why
The ability to switch models is the portfolio story. The eval can report quality against cost for a free model versus paid ones on the same questions. A hard credit cap is the simplest effective control against a public endpoint running up a bill.

## Consequences
- **Choosing specific models is deferred to its own decision.** The owner wants embedding and reranking that are very cheap *and* don't train on or retain inputs. That rules out free endpoints whose terms allow data collection, unless we decide otherwise. OpenRouter has account-level privacy settings and a per-request `data_collection: "deny"` option, which may meet this requirement; verify before choosing.
- Live users' questions will reach whichever providers we pick, and the UI disclaimer should say so.
- Free-tier request caps are per day and counted per request (reported as about 50/day for accounts with under $10 of purchased credit and about 1,000/day above that; check current limits). Running the full eval may need the higher tier.
- Batch embedding requests during ingestion, so the request count stays low.
- Revisit if a feature we need is provider-only, or if free endpoints prove too unreliable for the demo.
