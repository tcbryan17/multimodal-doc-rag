"""Contract for every Embedder (ADR 0012). Add real implementations to IMPLEMENTATIONS,
marked `live` when they call the network."""

import math
from collections.abc import Callable

import pytest

from multimodal_doc_rag.fakes import HashingEmbedder
from multimodal_doc_rag.protocols import Embedder


def _live_embedder() -> Embedder:
    from multimodal_doc_rag.config import Settings
    from multimodal_doc_rag.models.adapters import OpenRouterEmbedder
    from multimodal_doc_rag.models.openrouter import OpenRouterClient

    s = Settings()
    if s.openrouter_api_key is None:
        pytest.skip("OPENROUTER_API_KEY not set")
    return OpenRouterEmbedder.from_settings(s, OpenRouterClient.from_settings())


IMPLEMENTATIONS: list[object] = [
    pytest.param(lambda: HashingEmbedder(dim=64), id="fake-hashing"),
    pytest.param(_live_embedder, id="openrouter-embedder", marks=pytest.mark.live),
]

TEXTS = [
    "The altimeter measures height above a reference level.",
    "Net cash used in operating activities increased.",
    "",
]


@pytest.fixture(params=IMPLEMENTATIONS)
def embedder(request: pytest.FixtureRequest) -> Embedder:
    factory: Callable[[], Embedder] = request.param
    return factory()


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def test_model_key_names_the_dimension(embedder: Embedder) -> None:
    assert embedder.model_key.endswith(f"@{embedder.dim}")


def test_documents_one_unit_vector_each_of_the_right_dimension(embedder: Embedder) -> None:
    vectors = embedder.embed_documents(TEXTS)
    assert len(vectors) == len(TEXTS)
    for v in vectors:
        assert len(v) == embedder.dim
        assert _norm(v) == pytest.approx(1.0, abs=1e-3)


def test_query_is_a_unit_vector_of_the_right_dimension(embedder: Embedder) -> None:
    v = embedder.embed_query("What does the altimeter measure?")
    assert len(v) == embedder.dim
    assert _norm(v) == pytest.approx(1.0, abs=1e-3)


def test_deterministic(embedder: Embedder) -> None:
    assert embedder.embed_documents(TEXTS[:1]) == embedder.embed_documents(TEXTS[:1])


def test_related_text_is_closer_than_unrelated(embedder: Embedder) -> None:
    q = embedder.embed_query("What does an altimeter measure?")
    altimeter, cash, _ = embedder.embed_documents(TEXTS)
    assert _dot(q, altimeter) > _dot(q, cash)


def test_empty_batch(embedder: Embedder) -> None:
    assert embedder.embed_documents([]) == []
