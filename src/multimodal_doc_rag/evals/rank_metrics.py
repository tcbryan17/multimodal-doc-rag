"""Rank-aware retrieval metrics. REPORT ONLY: these must not become gates.

`recall_at_k` in `metrics.py` says whether a gold page is in the top k. It ignores where.
A system that puts the gold page at rank 1 and one that puts it at rank 5 score the same.
These metrics see rank. `gates.toml` is frozen (ADR 0016), so these appear in reports only,
and adding one as a gate needs a superseding ADR.

Options:
- Reciprocal rank (mean over questions is MRR): 1 / rank of the first hit, else 0. Why it
  works: the first relevant passage is what a reader needs most. Simple, but it ignores
  every hit after the first.
- nDCG@k: sum of gain / log2(rank + 1), divided by the best possible sum. The log discount
  makes early ranks count more, and the division puts the score between 0 and 1. Rewards
  getting several relevant passages high, which matters when a question needs two pages.
- Recall at several k (1, 3, 5, 10): easy to explain and already in the eval. Coarse, but it
  shows how much a larger context window would buy.

Gains. Binary (a passage covers a gold page or not) is what the gold set supports. Graded
gains would need the reviewer to rank pages by usefulness, which the gold set does not hold.

Multiple gold pages. A passage is relevant if `passage_covers` says it covers ANY gold page,
the same rule as `recall_at_k`. For nDCG, decide what the ideal ranking is: count each gold
page once, or each relevant passage once. A passage may span two gold pages, and two passages
may cover the same gold page. Pick one rule and write it down.

Both functions take a question that has gold pages. Return 0.0 for no hit. Raise ValueError
when k < 1, like `recall_at_k`.
"""

from collections.abc import Sequence

# Imported so the stubs share the exact coverage rule with recall_at_k.
from multimodal_doc_rag.evals.gold import GoldPage
from multimodal_doc_rag.evals.metrics import passage_covers  # noqa: F401
from multimodal_doc_rag.types import Passage


def reciprocal_rank(
    gold_pages: Sequence[GoldPage], passages: Sequence[Passage], k: int = 5
) -> float:
    """1 / rank (1-based) of the first of the top-k passages covering any gold page, else 0.0."""
    # TODO(human): scan passages[:k] with passage_covers and return 1 / rank of the first hit.
    raise NotImplementedError("TODO(human): first hit within k gives 1/rank, no hit gives 0.0")


def ndcg_at_k(gold_pages: Sequence[GoldPage], passages: Sequence[Passage], k: int = 5) -> float:
    """Binary-gain nDCG over the top-k passages, in [0, 1]."""
    # TODO(human): DCG of the binary hits divided by the DCG of the ideal ordering.
    raise NotImplementedError("TODO(human): DCG / ideal DCG with binary gains, 0.0 if no gold")
