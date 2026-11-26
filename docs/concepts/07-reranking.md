# 7. Reranking

## What it does
Hybrid search returns 30 candidates. The reranker reads the question together with each candidate and scores how well it answers, which is more accurate than comparing two separately made vectors. We use `qwen/qwen3-reranker-8b` through OpenRouter. `OpenRouterReranker.rerank` sorts the provider's scores again and caps the result to `top_n` locally, so it does not trust the provider to honour the cap. The pipeline keeps the top 5 (`top_k`) and replaces the RRF score with the reranker score. If the reranker fails, the pipeline falls back to the hybrid order, takes the first 5, and writes "rerank skipped: <error type>" in the trace. A spending-cap error is the one exception: it is re-raised, so a budget limit stops the run instead of quietly degrading it. The reranker sees `content` only, not the context header.

## Where it lives
- `src/multimodal_doc_rag/pipeline.py::RagPipeline._rerank`
- `src/multimodal_doc_rag/pipeline.py::RagPipeline.run`
- `src/multimodal_doc_rag/models/adapters.py::OpenRouterReranker`
- `src/multimodal_doc_rag/models/openrouter.py::OpenRouterClient.rerank`
- `src/multimodal_doc_rag/models/cost.py::BudgetExceededError`

## What was chosen and why
ADR 0009. qwen3-reranker-8b is the only zero-retention reranker in the catalogue checked on 2026-11-07, and it sits on a single provider (Fireworks). Its price showed as "0", most likely meaning unlisted, and the ADR says to verify it. Because there is one provider, an outage must cost quality, not availability. That is why `_rerank` catches any exception and falls back. The eval measures recall@5 with and without reranking, so the choice is tested, not assumed.

## Options rejected
| Option | Why rejected | When it would win |
|---|---|---|
| An LLM as reranker | Slower and dearer per call than a purpose-built reranker (reasoning in ADR 0009's option list, not a measured result) | If no private reranker existed |
| No reranker in v1 | The eval is meant to measure what reranking adds, so we keep it and compare | If the eval showed recall@5 unchanged |
| Fail the request when the reranker fails | One provider means one outage breaks `/ask` | Never for a live demo |
| A second reranker provider | None with zero retention existed on 2026-11-07 | If one appears (ADR 0009 says to revisit) |

## Evidence
- `tests/test_pipeline.py` has a test that reranker scores replace RRF scores and that `top_k` applies, plus the fallback path.
- Not measured yet: recall@5 with the reranker on against off. The pipeline has a `top_k` and a candidate count, but there is no "reranker off" switch in the eval runner today. Add one, run it on dev, and compare.
- Not measured yet: the reranker's real price. The figure smoke run's answering cost was $0.0031 per question, which includes it, but it is not broken out.

## Interview questions
1. Why rerank at all if hybrid search already ranks? What can a cross-encoder see that two separate vectors cannot?

**Your answer:**

2. Why does a reranker failure produce "rerank skipped" and not an error, while a budget error is re-raised?

**Your answer:**

3. Why fetch 30 candidates and keep 5? What goes wrong with 10 candidates, or with 100?

**Your answer:**

4. The reranker only sees `content`. What does it miss because of that, and what would you test?

**Your answer:**

5. There is one zero-retention reranker provider. How does that shape the design, and what would you change if it went away?

**Your answer:**
