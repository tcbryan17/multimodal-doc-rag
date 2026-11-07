import pytest

from multimodal_doc_rag.fakes import PlainTextParser
from multimodal_doc_rag.types import Chunk, Corpus, Element, Figure, PageRef, SourceInfo

P0, P1 = PageRef(0, "4-1"), PageRef(1, "4-2")
FIG = Figure(number="4-1", caption="Figure 4-1. Lift.", png=b"\x89PNG", width=1, height=1)


def test_page_idx_cannot_be_negative() -> None:
    with pytest.raises(ValueError):
        PageRef(-1, None)


def test_element_figure_iff_kind_figure() -> None:
    with pytest.raises(ValueError):
        Element(kind="figure", text="caption", page=P0, section_path=())
    with pytest.raises(ValueError):
        Element(kind="text", text="x", page=P0, section_path=(), figure=FIG)
    Element(kind="figure", text="", page=P0, section_path=(), figure=FIG)


def test_text_element_needs_text() -> None:
    with pytest.raises(ValueError):
        Element(kind="text", text="  ", page=P0, section_path=())


def test_chunk_page_range_and_embed_text() -> None:
    with pytest.raises(ValueError):
        Chunk(0, "text", (), page_start=P1, page_end=P0, content="x", context_header="h")
    chunk = Chunk(0, "text", (), page_start=P0, page_end=P1, content="body", context_header="h")
    assert chunk.embed_text == "h\n\nbody"


def test_plain_text_parser_pages_and_headings(tmp_path: object) -> None:
    from pathlib import Path

    path = Path(__file__).parent / "fixtures" / "plain_handbook.txt"
    doc = PlainTextParser().parse(path, SourceInfo("p", Corpus.FAA, "P", "file://p"))
    assert doc.page_count == 2
    stall = next(e for e in doc.elements if e.text.startswith("A stall"))
    assert stall.page == PageRef(1, "2")
    assert stall.section_path == ("Principles of Flight", "Stalls")
    altimeter = next(e for e in doc.elements if "altimeter" in e.text)
    assert altimeter.section_path == ("Flight Instruments",)
