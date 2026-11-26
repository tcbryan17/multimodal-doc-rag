# These tests define the contract Toby must meet. They are marked xfail(strict=True) so CI
# stays green while the function is a stub. Once you implement it, each test flips to a
# strict XPASS failure: that is your reminder to delete the xfail marker.
"""Contract tests for rank-aware retrieval metrics (hand-computed expected values)."""

import math

import pytest

from multimodal_doc_rag.evals.gold import GoldPage
from multimodal_doc_rag.evals.rank_metrics import ndcg_at_k, reciprocal_rank
from multimodal_doc_rag.types import PageRef, Passage

TODO = pytest.mark.xfail(
    raises=NotImplementedError, strict=True, reason="TODO(human): rank metrics"
)


def passage(cid: int, page: int, doc: str = "d1") -> Passage:
    return Passage(
        chunk_id=cid,
        doc_key=doc,
        doc_title=doc,
        kind="text",
        page_start=PageRef(page, None),
        page_end=PageRef(page, None),
        content="text",
        context_header="",
        score=1.0,
    )


def gp(page: int, doc: str = "d1") -> GoldPage:
    return GoldPage(doc=doc, page_idx=page)


MISS = [passage(1, 90), passage(2, 91), passage(3, 92)]


@TODO
def test_rr_hit_at_rank_1() -> None:
    assert reciprocal_rank([gp(5)], [passage(1, 5), *MISS]) == 1.0


@TODO
def test_rr_hit_at_rank_2() -> None:
    assert reciprocal_rank([gp(5)], [passage(1, 90), passage(2, 5)]) == 0.5


@TODO
def test_rr_hit_beyond_k_is_zero() -> None:
    ps = [*MISS, passage(4, 93), passage(5, 94), passage(6, 5)]
    assert reciprocal_rank([gp(5)], ps, k=5) == 0.0
    assert reciprocal_rank([gp(5)], ps, k=6) == pytest.approx(1 / 6)


@TODO
def test_rr_uses_first_hit_only() -> None:
    ps = [passage(1, 90), passage(2, 5), passage(3, 5)]
    assert reciprocal_rank([gp(5)], ps) == 0.5


@TODO
def test_rr_any_gold_page_counts() -> None:
    assert reciprocal_rank([gp(5), gp(7)], [passage(1, 90), passage(2, 7)]) == 0.5


@TODO
def test_rr_wrong_document_does_not_count() -> None:
    assert reciprocal_rank([gp(5, "d1")], [passage(1, 5, "d2")]) == 0.0


@TODO
def test_rr_rejects_k_below_one() -> None:
    with pytest.raises(ValueError):
        reciprocal_rank([gp(5)], MISS, k=0)


@TODO
def test_ndcg_hit_at_rank_1_is_one() -> None:
    assert ndcg_at_k([gp(5)], [passage(1, 5), *MISS]) == pytest.approx(1.0)


@TODO
def test_ndcg_single_gold_hit_at_rank_2() -> None:
    # DCG = 1 / log2(3); ideal DCG = 1 / log2(2) = 1.
    assert ndcg_at_k([gp(5)], [passage(1, 90), passage(2, 5)]) == pytest.approx(1 / math.log2(3))


@TODO
def test_ndcg_no_hit_is_zero() -> None:
    assert ndcg_at_k([gp(5)], MISS) == 0.0


@TODO
def test_ndcg_in_unit_interval() -> None:
    ps = [passage(1, 5), passage(2, 90), passage(3, 7)]
    assert 0.0 <= ndcg_at_k([gp(5), gp(7)], ps) <= 1.0


@TODO
def test_ndcg_prefers_earlier_hits() -> None:
    early = ndcg_at_k([gp(5)], [passage(1, 5), *MISS])
    late = ndcg_at_k([gp(5)], [*MISS, passage(4, 5)])
    assert early > late


@TODO
def test_ndcg_rejects_k_below_one() -> None:
    with pytest.raises(ValueError):
        ndcg_at_k([gp(5)], MISS, k=0)
