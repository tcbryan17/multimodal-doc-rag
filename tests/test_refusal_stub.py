# These tests define the contract Toby must meet. They are marked xfail(strict=True) so CI
# stays green while the function is a stub. Once you implement it, each test flips to a
# strict XPASS failure: that is your reminder to delete the xfail marker.
"""Contract tests for `refusal.decide_refusal` (option-independent invariants only)."""

import pytest

from multimodal_doc_rag.fakes import IDK
from multimodal_doc_rag.refusal import RefusalDecision, decide_refusal
from multimodal_doc_rag.types import PageRef, Passage

TODO = pytest.mark.xfail(raises=NotImplementedError, strict=True, reason="TODO(human): refusal")


def passage(cid: int, score: float = 1.0) -> Passage:
    return Passage(
        chunk_id=cid,
        doc_key="d1",
        doc_title="d1",
        kind="text",
        page_start=PageRef(0, "1"),
        page_end=PageRef(0, "1"),
        content="text",
        context_header="",
        score=score,
    )


def test_decision_is_frozen() -> None:
    d = RefusalDecision(refuse=True, reason="x")
    with pytest.raises(AttributeError):
        d.refuse = False  # type: ignore[misc]


@TODO
def test_no_passages_refuses() -> None:
    assert decide_refusal([], None, None, []).refuse is True


@TODO
def test_no_passages_refuses_with_scores_too() -> None:
    assert decide_refusal([], [], None, []).refuse is True


@TODO
def test_reason_is_non_empty() -> None:
    d = decide_refusal([], None, None, [])
    assert d.reason.strip()


@TODO
def test_answer_with_valid_citation_is_not_refused() -> None:
    # Holds for every option: strong passage, cited answer. Use a high score so a floor passes.
    ps = [passage(1, 0.99)]
    assert decide_refusal(ps, [0.99], "Revenue was 5 [1].", [1]).refuse is False


@TODO
def test_idk_answer_is_not_turned_into_a_different_refusal_reason() -> None:
    # The model's own IDK has no citations. Whatever you choose, the decision must not crash.
    d = decide_refusal([passage(1)], [0.9], IDK, [])
    assert isinstance(d, RefusalDecision)


@TODO
def test_fallback_path_without_scores_does_not_crash() -> None:
    d = decide_refusal([passage(1)], None, "Revenue was 5 [1].", [1])
    assert isinstance(d, RefusalDecision)


# Option-specific expectations. Uncomment the one(s) for the option you choose.
# (b/d) @TODO def test_low_top_score_refuses_before_generation():
#           decide_refusal([passage(1, 0.01)], [0.01], None, []).refuse is True  (floor-dependent)
# (c/d) @TODO def test_uncited_non_idk_answer_refuses():
#           decide_refusal([passage(1, 0.9)], [0.9], "Revenue was 5.", []).refuse is True
# (a)   status quo: decide_refusal never refuses when passages exist.
