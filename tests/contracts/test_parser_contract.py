"""Contract for every Parser (ADR 0006/0012). Each case pairs a parser with a fixture file
it understands; add the EDGAR and PDF parsers here with their fixtures."""

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from multimodal_doc_rag.fakes import PlainTextParser
from multimodal_doc_rag.protocols import Parser
from multimodal_doc_rag.types import Corpus, ParsedDocument, SourceInfo

FIXTURES = Path(__file__).parent.parent / "fixtures"

CASES: list[object] = [
    # Each case is one (parser factory, fixture file, SourceInfo) tuple.
    pytest.param(
        (
            PlainTextParser,
            FIXTURES / "plain_handbook.txt",
            SourceInfo(doc_key="plain", corpus=Corpus.FAA, title="Plain", source_url="file://p"),
        ),
        id="fake-plaintext",
    ),
]


@pytest.fixture(params=CASES)
def parsed(request: pytest.FixtureRequest) -> ParsedDocument:
    factory: Callable[[], Parser]
    factory, path, source = request.param
    return factory().parse(path, source)


def test_has_elements_and_keeps_source(parsed: ParsedDocument) -> None:
    assert parsed.elements
    assert parsed.page_count >= 1
    assert re.fullmatch(r"[0-9a-f]{64}", parsed.sha256)


def test_pages_are_in_range_and_in_reading_order(parsed: ParsedDocument) -> None:
    idxs = [e.page.idx for e in parsed.elements]
    assert all(0 <= i < parsed.page_count for i in idxs)
    assert idxs == sorted(idxs)


def test_every_element_has_a_section_path(parsed: ParsedDocument) -> None:
    # The first element may precede any heading, but most should sit under one.
    with_path = sum(1 for e in parsed.elements if e.section_path)
    assert with_path >= len(parsed.elements) // 2


def test_figures_carry_a_png(parsed: ParsedDocument) -> None:
    for e in parsed.elements:
        if e.figure is not None:
            assert e.figure.png.startswith(b"\x89PNG")
            assert e.figure.width > 0 and e.figure.height > 0
