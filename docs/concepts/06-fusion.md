# 6. Fusion

## What it does
Fusion merges the vector list and the keyword list into one ranking. We use Reciprocal Rank Fusion. Each chunk scores `1 / (k + rank)` in every list it appears in, with `k = 60` and rank starting at 1, and the scores are added. A chunk in both lists beats a chunk in one. With rankings `[[7, 3], [3, 9]]`, chunk 3 scores 1/62 + 1/61 = 0.03252, chunk 7 scores 0.01639 and chunk 9 scores 0.01613. Ties break by first appearance, so output is deterministic. `hybrid_search` runs both searches, fuses them, keeps the top 30 and loads the passages. The score stored on each passage is the RRF score.

## Where it lives
- `src/multimodal_doc_rag/search.py::rrf`
- `src/multimodal_doc_rag/search.py::hybrid_search`
- `src/multimodal_doc_rag/search.py::fetch_passages`
- `src/multimodal_doc_rag/pipeline.py::RagPipeline.run`

## What was chosen and why
ADR 0010. RRF works on ranks, not scores. Cosine distances live in [0, 2], and `ts_rank_cd` values are unbounded and depend on document length. Adding or normalising them would let one list dominate arbitrarily, while a rank means the same thing in any list. RRF is standard and needs no tuning. Because fusion is by rank, the quirks of `ts_rank_cd` scoring matter less. The reranker then takes the top 30 fused candidates (see guide 7).

## Options rejected
| Option | Why rejected | When it would win |
|---|---|---|
| Weighted sum of normalised scores | Not listed in ADR 0010. The ADR's reasoning applies: the two score scales are incomparable, and a weight needs tuning. | If we had a labelled set big enough to tune the weight |
| Vector only | Misses exact-term matches | A purely semantic corpus |
| Learned fusion | Not listed in ADR 0010. More moving parts, and we already rerank after fusion. | If fusion were the measured bottleneck |
| A different `k` | Not tried and not in the ADR. A larger `k` flattens the gap between top ranks. | If the eval showed the top ranks of one list were too dominant |

## Evidence
- `rrf` has a worked example in its docstring, and unit tests cover ties and determinism.
- Not measured yet: recall@5 and recall@30 for fused against each list alone, and whether `k = 60` is better than another value. To measure it, run the eval with each ranking list switched off and with `k` swept over a few values on the dev split only.

## Interview questions
1. Why fuse ranks instead of scores? Walk through the example with chunks 3, 7 and 9.

**Your answer:**

2. What does `k = 60` do? What changes if you set it to 1 or 1,000?

**Your answer:**

3. A chunk is rank 1 in the vector list and absent from the keyword list. Another is rank 5 in both. Which wins, and is that what you want?

**Your answer:**

4. How would you show that hybrid beats vector alone on this corpus, with the eval you have?

**Your answer:**

5. Why does the pipeline fuse 30 candidates when only 5 reach the generator?

**Your answer:**
