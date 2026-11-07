"""Contract for every Reranker (ADR 0012)."""

from collections.abc import Callable

import pytest

from multimodal_doc_rag.fakes import OverlapReranker
from multimodal_doc_rag.protocols import Reranker


def _live_reranker() -> Reranker:
    from multimodal_doc_rag.config import Settings
    from multimodal_doc_rag.models.adapters import OpenRouterReranker
    from multimodal_doc_rag.models.openrouter import OpenRouterClient

    s = Settings()
    if s.openrouter_api_key is None:
        pytest.skip("OPENROUTER_API_KEY not set")
    return OpenRouterReranker(OpenRouterClient.from_settings(), s.rerank_model)


IMPLEMENTATIONS: list[object] = [
    pytest.param(OverlapReranker, id="fake-overlap"),
    pytest.param(_live_reranker, id="openrouter-reranker", marks=pytest.mark.live),
]

DOCS = [
    "Revenue grew 6% year over year.",
    "The altimeter measures altitude above mean sea level.",
    "A stall occurs when the critical angle of attack is exceeded.",
    "The airspeed indicator shows indicated airspeed.",
]


@pytest.fixture(params=IMPLEMENTATIONS)
def reranker(request: pytest.FixtureRequest) -> Reranker:
    factory: Callable[[], Reranker] = request.param
    return factory()


def test_returns_at_most_top_n_valid_unique_indices(reranker: Reranker) -> None:
    result = reranker.rerank("what does the altimeter measure", DOCS, top_n=2)
    assert len(result) == 2
    indices = [i for i, _ in result]
    assert len(set(indices)) == len(indices)
    assert all(0 <= i < len(DOCS) for i in indices)


def test_sorted_best_first(reranker: Reranker) -> None:
    scores = [s for _, s in reranker.rerank("altimeter altitude", DOCS, top_n=len(DOCS))]
    assert scores == sorted(scores, reverse=True)


def test_most_relevant_document_ranks_first(reranker: Reranker) -> None:
    (best, _), *_ = reranker.rerank("what does the altimeter measure", DOCS, top_n=4)
    assert best == 1


def test_top_n_larger_than_input(reranker: Reranker) -> None:
    assert len(reranker.rerank("stall", DOCS[:2], top_n=10)) == 2


def test_empty_documents(reranker: Reranker) -> None:
    assert reranker.rerank("anything", [], top_n=5) == []
