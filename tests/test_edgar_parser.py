"""EDGAR parser tests, against the hand-written fixture tests/fixtures/mini_10k.html."""

import hashlib
from pathlib import Path

import pytest

from multimodal_doc_rag.parsing.edgar import EdgarHtmlParser
from multimodal_doc_rag.types import Corpus, ParsedDocument, SourceInfo

FIXTURE = Path(__file__).parent / "fixtures" / "mini_10k.html"
SOURCE = SourceInfo(
    doc_key="example-10k-2025",
    corpus=Corpus.TEN_K,
    title="Example Corp 10-K FY2025",
    source_url="file://mini_10k.html",
    company="Example Corp",
    fiscal_year=2025,
)

EXPECTED_TABLE = (
    "|  | 2025 | 2024 |\n"
    "| --- | --- | --- |\n"
    "| Net sales | $1,200 | $1,000 |\n"
    "| Net income (loss) | $(45) | $30 |"
)


@pytest.fixture(scope="module")
def doc() -> ParsedDocument:
    return EdgarHtmlParser().parse(FIXTURE, SOURCE)


def test_page_labels(doc: ParsedDocument) -> None:
    labels: dict[int, str | None] = {e.page.idx: e.page.label for e in doc.elements}
    assert doc.page_count == 5
    assert labels == {0: None, 1: "1", 2: "2", 3: "3", 4: "F-1"}


def test_cover_has_no_label(doc: ParsedDocument) -> None:
    cover = [e for e in doc.elements if e.page.idx == 0]
    assert cover
    assert all(e.page.label is None for e in cover)


def test_footers_are_not_elements(doc: ParsedDocument) -> None:
    assert not any(e.text in {"1", "2", "3", "F-1"} for e in doc.elements)


def test_section_paths(doc: ParsedDocument) -> None:
    by_text = {e.text: e.section_path for e in doc.elements}
    assert by_text["Annual report for the fiscal year ended December 31, 2025"] == ()
    business = next(p for t, p in by_text.items() if t.startswith("Example Corp designs"))
    assert business == ("Item 1. Business",)
    risk = next(p for t, p in by_text.items() if t.startswith("Demand for widgets"))
    assert risk == ("Item 1A. Risk Factors",)
    # The bold standalone line becomes a level-2 heading for what follows.
    supplier = next(p for t, p in by_text.items() if t.startswith("We rely on a single"))
    assert supplier == ("Item 1A. Risk Factors", "Supply Chain Risks")
    mdna = next(p for t, p in by_text.items() if t.startswith("Net sales increased"))
    assert mdna == ("Item 7. Management’s Discussion and Analysis",)  # sub-heading reset


def test_headings_are_not_elements(doc: ParsedDocument) -> None:
    texts = [e.text for e in doc.elements]
    assert not any(t.startswith(("Item", "PART", "Supply Chain")) for t in texts)


def test_table_markdown(doc: ParsedDocument) -> None:
    tables = [e for e in doc.elements if e.kind == "table"]
    assert len(tables) == 1
    assert tables[0].text == EXPECTED_TABLE
    assert tables[0].page.label == "3"


def test_whitespace_and_nbsp_are_normalised(doc: ParsedDocument) -> None:
    text = [e.text for e in doc.elements if e.kind == "text"]
    assert all("\xa0" not in t and "  " not in t for t in text)
    assert any("key component. A disruption" in t for t in text)  # nbsp became a plain space


def test_hidden_xbrl_is_excluded(doc: ParsedDocument) -> None:
    joined = " ".join(e.text for e in doc.elements)
    assert "HIDDEN-XBRL-CONTEXT" not in joined
    assert "0000000000" not in joined


def test_reading_order_and_split_paragraph(doc: ParsedDocument) -> None:
    texts = [e.text for e in doc.elements]
    first = next(i for i, t in enumerate(texts) if t.endswith("could reduce our"))
    # A paragraph split by a page break is two consecutive elements on consecutive pages.
    assert texts[first + 1] == "revenue and harm our operating results."
    assert doc.elements[first + 1].page.idx == doc.elements[first].page.idx + 1
    table = next(i for i, e in enumerate(doc.elements) if e.kind == "table")
    assert texts[table - 1].startswith("Net sales increased")
    assert doc.elements[-1].page.label == "F-1"
    idxs = [e.page.idx for e in doc.elements]
    assert idxs == sorted(idxs)


def test_sha256_is_of_file_bytes_and_stable(doc: ParsedDocument) -> None:
    again = EdgarHtmlParser().parse(FIXTURE, SOURCE)
    assert doc.sha256 == again.sha256 == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
