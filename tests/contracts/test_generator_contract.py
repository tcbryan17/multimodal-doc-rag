"""Contract for every Generator (ADR 0012): grounded citations, and "I don't know" with nothing."""

from collections.abc import Callable

import pytest

from multimodal_doc_rag.fakes import EchoGenerator
from multimodal_doc_rag.protocols import Generator
from multimodal_doc_rag.types import PageRef, Passage

IMPLEMENTATIONS: list[object] = [
    pytest.param(EchoGenerator, id="fake-echo"),
]


def _passage(chunk_id: int, content: str) -> Passage:
    page = PageRef(idx=3, label="8-4")
    return Passage(
        chunk_id=chunk_id,
        doc_key="phak-ch8",
        doc_title="FAA-H-8083-25C, Ch. 8: Flight Instruments",
        kind="text",
        page_start=page,
        page_end=page,
        content=content,
        context_header="FAA-H-8083-25C › Ch. 8 › Altimeter",
        score=1.0,
    )


PASSAGES = [
    _passage(101, "The altimeter measures the height of an aircraft above a given level."),
    _passage(102, "The vertical speed indicator shows the rate of climb or descent."),
]


@pytest.fixture(params=IMPLEMENTATIONS)
def generator(request: pytest.FixtureRequest) -> Generator:
    factory: Callable[[], Generator] = request.param
    return factory()


def test_cites_only_passages_it_was_given(generator: Generator) -> None:
    answer = generator.generate("What does the altimeter measure?", PASSAGES, figures={})
    assert answer.text.strip()
    assert answer.cited_chunk_ids
    assert set(answer.cited_chunk_ids) <= {p.chunk_id for p in PASSAGES}


def test_no_passages_means_i_dont_know_and_no_citations(generator: Generator) -> None:
    answer = generator.generate("What does the altimeter measure?", [], figures={})
    assert answer.cited_chunk_ids == ()
    assert "don't know" in answer.text.lower() or "do not know" in answer.text.lower()
