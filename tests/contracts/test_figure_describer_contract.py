"""Contract for every FigureDescriber (ADR 0008)."""

from collections.abc import Callable

import pytest

from multimodal_doc_rag.fakes import CaptionFigureDescriber
from multimodal_doc_rag.protocols import FigureDescriber


def _live_figure_describer() -> FigureDescriber:
    from multimodal_doc_rag.config import Settings
    from multimodal_doc_rag.models.adapters import OpenRouterFigureDescriber
    from multimodal_doc_rag.models.openrouter import OpenRouterClient

    s = Settings()
    if s.openrouter_api_key is None:
        pytest.skip("OPENROUTER_API_KEY not set")
    return OpenRouterFigureDescriber(OpenRouterClient.from_settings(), s.generation_model)


IMPLEMENTATIONS: list[object] = [
    pytest.param(CaptionFigureDescriber, id="fake-caption"),
    pytest.param(_live_figure_describer, id="openrouter-describer", marks=pytest.mark.live),
]

# Smallest valid PNG (1x1 transparent pixel), so the contract needs no image fixtures.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)


@pytest.fixture(params=IMPLEMENTATIONS)
def describer(request: pytest.FixtureRequest) -> FigureDescriber:
    factory: Callable[[], FigureDescriber] = request.param
    return factory()


def test_informational_figures_get_a_description(describer: FigureDescriber) -> None:
    result = describer.describe(TINY_PNG, "Figure 8-22. Turn coordinator in a slip.", "")
    assert isinstance(result.informational, bool)
    if result.informational:
        assert result.description.strip()


def test_returns_a_bool_for_uncaptioned_images(describer: FigureDescriber) -> None:
    result = describer.describe(TINY_PNG, "", "")
    assert isinstance(result.informational, bool)
