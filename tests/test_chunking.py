import random
import re
from pathlib import Path

import pytest

from multimodal_doc_rag.chunking import chunk_document, context_header, count_tokens
from multimodal_doc_rag.fakes import PlainTextParser
from multimodal_doc_rag.types import (
    Chunk,
    Corpus,
    Element,
    Figure,
    PageRef,
    ParsedDocument,
    SourceInfo,
)

SOURCE = SourceInfo(doc_key="d", corpus=Corpus.FAA, title="Doc", source_url="file://d")
SEC_A = ("A",)
SEC_B = ("A", "B")


def page(i: int) -> PageRef:
    return PageRef(idx=i, label=str(i + 1))


def text(t: str, p: int = 0, sec: tuple[str, ...] = SEC_A) -> Element:
    return Element(kind="text", text=t, page=page(p), section_path=sec)


def doc(*elements: Element) -> ParsedDocument:
    return ParsedDocument(source=SOURCE, sha256="0" * 64, page_count=10, elements=elements)


def make_figure(caption: str = "Figure 1. A gauge") -> Figure:
    return Figure(number="1", caption=caption, png=b"x", width=1, height=1)


def test_count_tokens_is_ceil_chars_over_4() -> None:
    assert count_tokens("") == 0
    assert count_tokens("abcd") == 1
    assert count_tokens("abcde") == 2


def test_context_header_format() -> None:
    assert context_header("Doc", ("Ch 1", "Stalls")) == "Doc › Ch 1 › Stalls"
    assert context_header("Doc", ()) == "Doc"


def test_chunk_uses_title_and_section_path_in_header() -> None:
    [c] = chunk_document(doc(text("hello", sec=SEC_B)))
    assert c.context_header == "Doc › A › B"
    assert c.section_path == SEC_B


def test_small_paragraphs_merge_with_blank_line() -> None:
    chunks = chunk_document(doc(text("one."), text("two."), text("three.")))
    assert [c.content for c in chunks] == ["one.\n\ntwo.\n\nthree."]


def test_section_change_splits() -> None:
    chunks = chunk_document(doc(text("one."), text("two.", sec=SEC_B), text("three.", sec=SEC_B)))
    assert [c.content for c in chunks] == ["one.", "two.\n\nthree."]
    assert [c.section_path for c in chunks] == [SEC_A, SEC_B]


def test_page_range_across_page_break() -> None:
    [c] = chunk_document(doc(text("one.", p=3), text("two.", p=4)))
    assert c.page_start == page(3)
    assert c.page_end == page(4)


def test_merge_stops_before_exceeding_max() -> None:
    # 40 chars = 10 tokens each; the two joined (82 chars = 21 tokens) exceed 20 but not 21.
    a, b = "a" * 40, "b" * 40
    assert [c.content for c in chunk_document(doc(text(a), text(b)), max_tokens=20)] == [a, b]
    assert len(chunk_document(doc(text(a), text(b)), max_tokens=21)) == 1


def test_oversized_paragraph_splits_at_sentences() -> None:
    sentences = [f"Sentence number {i} is here." for i in range(10)]
    chunks = chunk_document(doc(text(" ".join(sentences))), max_tokens=20)
    assert len(chunks) > 1
    for c in chunks:
        assert count_tokens(c.content) <= 20
        assert c.content.endswith(".")  # never cut mid-sentence
    assert " ".join(c.content for c in chunks) == " ".join(sentences)


def test_oversized_sentence_falls_back_to_hard_split() -> None:
    chunks = chunk_document(doc(text("x" * 100)), max_tokens=10)
    assert [c.content for c in chunks] == ["x" * 40, "x" * 40, "x" * 20]


def test_table_is_own_chunk() -> None:
    table = "| a | b |\n| - | - |\n| 1 | 2 |"
    chunks = chunk_document(doc(text("before"), Element("table", table, page(0), SEC_A), text("x")))
    assert [c.kind for c in chunks] == ["text", "table", "text"]
    assert chunks[1].content == table


def test_table_splits_by_rows_repeating_header() -> None:
    header = "| Item | Value |\n| --- | --- |"
    rows = [f"| row{i} | {i} |" for i in range(6)]
    table = "\n".join([header, *rows])
    chunks = chunk_document(doc(Element("table", table, page(2), SEC_A)), max_tokens=20)
    assert [c.content for c in chunks] == [
        header + "\n" + "\n".join(rows[0:3]),
        header + "\n" + "\n".join(rows[3:6]),
    ]
    assert all(c.kind == "table" for c in chunks)


def test_oversized_table_row_is_kept_whole() -> None:
    header = "| K | V |\n| - | - |"
    big = "| " + "z" * 100 + " | 1 |"
    table = "\n".join([header, "| a | 1 |", big, "| b | 2 |"])
    chunks = chunk_document(doc(Element("table", table, page(0), SEC_A)), max_tokens=10)
    assert any(big in c.content for c in chunks)
    assert all(c.content.startswith(header) for c in chunks)


def test_figure_is_own_chunk_with_figure_carried() -> None:
    fig = make_figure()
    el = Element("figure", "Figure 1. A gauge", page(1), SEC_A, figure=fig)
    chunks = chunk_document(doc(text("before"), el, text("after")))
    assert [c.kind for c in chunks] == ["text", "figure", "text"]
    f = chunks[1]
    assert f.figure is fig
    assert f.content == "Figure 1. A gauge"
    assert f.informational is None
    assert f.page_start == f.page_end == page(1)


def test_uncaptioned_figure_still_has_content() -> None:
    el = Element("figure", "", page(0), SEC_A, figure=make_figure(""))
    [c] = chunk_document(doc(el))
    assert c.content == "Figure 1"


def test_invalid_max_tokens() -> None:
    with pytest.raises(ValueError):
        chunk_document(doc(text("x")), max_tokens=0)


def test_empty_document() -> None:
    assert chunk_document(doc()) == []


def _invariants(chunks: list[Chunk], max_tokens: int) -> None:
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    for c in chunks:
        assert c.content.strip()
        # Text always fits. Tables fit too in these tests because every generated row is
        # far smaller than the budget (an oversized single row is the tested exception).
        assert count_tokens(c.content) <= max_tokens


def test_plain_handbook_fixture() -> None:
    path = Path(__file__).parent / "fixtures" / "plain_handbook.txt"
    parsed = PlainTextParser().parse(path, SOURCE)
    chunks = chunk_document(parsed)
    _invariants(chunks, 500)
    # Small sections: exactly one chunk per distinct section path, in reading order.
    assert len({c.section_path for c in chunks}) == len(chunks)
    assert all(c.context_header.startswith("Doc") for c in chunks)
    for el in parsed.elements:
        assert any(el.text in c.content for c in chunks)


def _random_doc(seed: int) -> ParsedDocument:
    rnd = random.Random(seed)
    elements: list[Element] = []
    for i in range(rnd.randint(5, 30)):
        sec = rnd.choice([(), SEC_A, SEC_B])
        pg = i // 3
        roll = rnd.random()
        if roll < 0.6:
            words = [f"w{rnd.randint(0, 99)}" for _ in range(rnd.randint(1, 120))]
            sentences = [" ".join(words[j : j + 7]) + "." for j in range(0, len(words), 7)]
            elements.append(text(" ".join(sentences), pg, sec))
        elif roll < 0.85:
            rows = [f"| r{i}_{k} | {rnd.randint(0, 9999)} |" for k in range(rnd.randint(1, 30))]
            table = "\n".join(["| K | V |", "| --- | --- |", *rows])
            elements.append(Element("table", table, page(pg), sec))
        else:
            cap = f"Figure {i}. caption"
            fig = Figure(number=str(i), caption=cap, png=b"", width=1, height=1)
            elements.append(Element("figure", cap, page(pg), sec, figure=fig))
    return doc(*elements)


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("max_tokens", [32, 256, 1024])
def test_no_text_is_lost(seed: int, max_tokens: int) -> None:
    parsed = _random_doc(seed)
    chunks = chunk_document(parsed, max_tokens=max_tokens)
    _invariants(chunks, max_tokens)

    def squash(s: str) -> str:
        return re.sub(r"\s+", "", s)

    # Split text is re-joined with different whitespace, so compare with whitespace removed.
    body = squash("".join(c.content for c in chunks if c.kind != "table"))
    table_lines = {ln for c in chunks if c.kind == "table" for ln in c.content.splitlines()}
    for el in parsed.elements:
        if el.kind == "table":
            assert set(el.text.splitlines()) <= table_lines
        else:
            assert squash(el.text) in body
    # Reading order: chunks never move backwards through the document.
    pages = [c.page_start.idx for c in chunks]
    assert pages == sorted(pages)


def test_max_tokens_changes_chunk_count() -> None:
    # 12 paragraphs of ~120 tokens in one section: 2 per chunk at 256, all in one at 1024.
    parsed = doc(*(text(f"{i:02d} " + "w" * 477, p=i) for i in range(12)))
    small = chunk_document(parsed, max_tokens=256)
    large = chunk_document(parsed, max_tokens=1024)
    assert len(small) > len(large)
