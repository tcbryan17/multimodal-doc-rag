# Eval report: judge-smoke-figures

## Configuration

| setting | value |
|---|---|
| started (UTC) | 2026-11-15T14:16:59Z |
| git commit | 9afaf88f33e168f4a02cc53ea6fa8e295e250961 (uncommitted changes) |
| corpus / split | faa / dev |
| generator | anthropic/claude-haiku-5.5 (reasoning off) |
| judge | openai/gpt-6-luna (fingerprint e2a908a51730) |
| embedder | qwen/qwen3-embedding-8b |
| reranker | qwen/qwen3-reranker-8b |
| retrieval scope | all documents (the product default) |
| figure images | sent to the generator and the judge |
| top_k / recall_k / candidates | 5 / 5 / 30 |
| limit | 3 |
| question types | figure |
| database | rag |
| index | documents=25, chunks=3449, mean_chunk_chars=973.5, max_chunk_chars=3424, chunks_embedded=3449, embedding_key=qwen/qwen3-embedding-8b@1024 |
| cost cap | $2.00 |
| spend | $0.0112 of $2.00 cap over 12 calls (12 reported, 0 estimated from tokens, 0 charged the flat fallback) |

Questions answered: 3 of 3 attempted (0 errors, 0 judge failures).

## Metrics (mean, 95% bootstrap CI, n = questions where defined)

| group | recall@5 | citation acc. | numeric match | correctness | faithfulness | abstains (unanswerable) | false abstain (answerable) |
|---|---|---|---|---|---|---|---|
| overall | 1.00 [1.00, 1.00] (n=3) | 1.00 [1.00, 1.00] (n=3) | 1.00 [1.00, 1.00] (n=3) | 1.00 [1.00, 1.00] (n=3) | 1.00 [1.00, 1.00] (n=3) | - | 0.00 [0.00, 0.00] (n=3) |
| faa | 1.00 [1.00, 1.00] (n=3) | 1.00 [1.00, 1.00] (n=3) | 1.00 [1.00, 1.00] (n=3) | 1.00 [1.00, 1.00] (n=3) | 1.00 [1.00, 1.00] (n=3) | - | 0.00 [0.00, 0.00] (n=3) |
| faa / dev | 1.00 [1.00, 1.00] (n=3) | 1.00 [1.00, 1.00] (n=3) | 1.00 [1.00, 1.00] (n=3) | 1.00 [1.00, 1.00] (n=3) | 1.00 [1.00, 1.00] (n=3) | - | 0.00 [0.00, 0.00] (n=3) |
| faa / dev / figure | 1.00 [1.00, 1.00] (n=3) | 1.00 [1.00, 1.00] (n=3) | 1.00 [1.00, 1.00] (n=3) | 1.00 [1.00, 1.00] (n=3) | 1.00 [1.00, 1.00] (n=3) | - | 0.00 [0.00, 0.00] (n=3) |

## Cost and latency

| group | answering cost per question (mean / p50 / p95) | latency (mean / p50 / p95) |
|---|---|---|
| overall | 0.00310 / 0.00300 / 0.00346 USD | 3448 / 3836 / 4035 ms |
| faa | 0.00310 / 0.00300 / 0.00346 USD | 3448 / 3836 / 4035 ms |
| faa / dev | 0.00310 / 0.00300 / 0.00346 USD | 3448 / 3836 / 4035 ms |
| faa / dev / figure | 0.00310 / 0.00300 / 0.00346 USD | 3448 / 3836 / 4035 ms |

## Release gates (ADR 0016)

> **Guidance only.** This run can't decide release: dev split, not held-out: gates bind only on the held-out run; covers faa only: the binding run needs both corpora; --limit 3: not the full question set; only figure questions: not the full question set; uncommitted changes: the run can't be tied to a commit.

| gate | group | value | n | threshold | status |
|---|---|---|---|---|---|
| recall_at_5 | faa | 1.00 | 3 | ≥ 0.80 | pass |
| citation_accuracy | faa | 1.00 | 3 | ≥ 0.90 | pass |
| faithfulness | faa | 1.00 | 3 | ≥ 0.90 | pass |
| correctness | faa | 1.00 | 3 | ≥ 0.75 | pass |
| false_abstention | faa | 0.00 | 3 | ≤ 0.10 | pass |
| abstention | pooled | - | 0 | ≥ 0.80 | not measured |
| cost_per_question | faa | $0.0031 | 3 | ≤ $0.0050 | pass |
| latency_p95 | faa | 4,035 ms | 3 | ≤ 8,000 ms | pass |

## Failures for error analysis

### Retrieval misses (no gold page in the top-k): 0


### Wrong or partly wrong answers (judge correctness < 1): 0


### Numbers missing from the answer: 0


### False abstentions (answerable, but the system said it didn't know): 0


### Unanswerable questions that got an answer: 0


### Errors (the question could not be answered): 0
