# 10. Retrieval metrics

## What it does
Retrieval is scored by page, not by text. `passage_covers` is true when a retrieved passage is from the gold page's document and its page-index range includes the gold page. A chunk may span a page break, so it is a range. `recall_at_k` is a hit if any of the first k passages covers any gold page (k = 5, the gate's value). So recall here is a hit rate per question, not the share of gold pages found. `citation_accuracy` is the share of the answer's cited passages that cover a gold page, or `None` if the answer cites nothing. Pages are compared by 0-based index, never by printed label, because labels such as "4-9" and "4-12" do not sort and some pages have none. Scores are averaged with `mean_ci`, a percentile bootstrap: 2,000 resamples, seed 0, 95% interval. The interval is wide with about 60 questions, which is the honest picture. There is no rank-aware metric, so a hit at rank 1 and a hit at rank 5 score the same.

## Where it lives
- `src/multimodal_doc_rag/evals/metrics.py::passage_covers`
- `src/multimodal_doc_rag/evals/metrics.py::recall_at_k`
- `src/multimodal_doc_rag/evals/metrics.py::citation_accuracy`
- `src/multimodal_doc_rag/evals/metrics.py::item_metrics`
- `src/multimodal_doc_rag/evals/metrics.py::mean_ci`
- `src/multimodal_doc_rag/evals/metrics.py::metric_table`
- `src/multimodal_doc_rag/evals/rank_metrics.py::reciprocal_rank` (gap: stub)
- `src/multimodal_doc_rag/evals/rank_metrics.py::ndcg_at_k` (gap: stub)

## What was chosen and why
ADR 0011 defines recall@5 as "a gold page falls within a top-5 chunk's page-index range", and ADR 0007 is why a range is needed. The gold set stores page references, not chunk ids, so the score survives a change of chunk size. That is what lets the 256 / 512 / 1024 comparison work. The gate is recall@5 at or above 0.80 per corpus, set before any result (ADR 0016). The bootstrap interval is reported next to every number, and a gate passes on the point estimate. The gap: recall@5 cannot tell a better ranker from a worse one when both put the answer somewhere in the top 5. MRR and nDCG would. The stubs are there for Toby to decide whether and how to add them.

## Options rejected
| Option | Why rejected | When it would win |
|---|---|---|
| Match by chunk id | Gold would break whenever chunking changes | A fixed chunking with a stable id scheme |
| Match by text overlap | Not in the ADRs. Fuzzy, and hard to explain | Gold built from passages, not pages |
| Compare printed labels | Labels do not sort and some are missing | Never |
| Gate on the lower CI bound | Close to unpassable with about 20 held-out questions (ADR 0016) | A much larger held-out set |
| MRR and nDCG now | Not built. The gate is defined as recall@5. | If ranker comparisons come out too close to call on recall@5 |

## Evidence
- `tests/test_evals_metrics.py` pins the metric functions.
- Figure smoke run: recall@5 of 1.00 over 3 questions (`evals/reports/20261115T141659Z-judge-smoke-figures.md`). That is too small to mean anything.
- Not measured yet: recall@5 on the full dev set (118 verified questions), and every comparison that depends on it. The dev baseline (`scripts/run_eval.py --label baseline`) is next in `docs/next-steps.md`.

## Interview questions
1. Why is recall@5 judged by page range and not by chunk id? What does that buy you in the chunk-size comparison?

**Your answer:**

2. A question has two gold pages and the top 5 hold one of them. Is that a hit? Why did you choose "any" on both sides?

**Your answer:**

3. Recall@5 scores a hit at rank 1 the same as at rank 5. What metric fixes that, and what does it need from the gold set?

**Your answer:**

4. What does the 95% bootstrap interval say about a run of 20 held-out questions, and why not gate on its lower bound?

**Your answer:**

5. Retrieval is unfiltered in the binding run. How does that change what recall@5 measures, and why is it the right choice?

**Your answer:**
