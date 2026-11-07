"""HandbookPdfParser: layout rules on a synthetic PDF, plus regression runs on the real chapters.

The synthetic PDF is generated at test time (tests/fixtures/make_mini_handbook.py). The real
chapters are large and never committed; those tests skip unless the FAA_PDF_DIR environment
variable points at a folder holding them.
"""

import importlib.util
import os
import re
import struct
from pathlib import Path

import pytest

from multimodal_doc_rag.parsing.handbook_pdf import FOOTER_LABEL, HandbookPdfParser
from multimodal_doc_rag.types import Corpus, Element, ParsedDocument, SourceInfo

_spec = importlib.util.spec_from_file_location(
    "make_mini_handbook", Path(__file__).parent / "fixtures" / "make_mini_handbook.py"
)
assert _spec is not None and _spec.loader is not None
mini = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mini)

SOURCE = SourceInfo(doc_key="faa-test", corpus=Corpus.FAA, title="Test", source_url="file://t")
CHAPTER = "Aerodynamics of Flight"


def _png_size(png: bytes) -> tuple[int, int]:
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    w, h = struct.unpack(">II", png[16:24])
    return int(w), int(h)


@pytest.fixture(scope="module")
def doc(tmp_path_factory: pytest.TempPathFactory) -> ParsedDocument:
    path = tmp_path_factory.mktemp("mini") / "mini.pdf"
    mini.build(path)
    return HandbookPdfParser().parse(path, SOURCE)


def _figures(doc: ParsedDocument) -> dict[str | None, Element]:
    return {e.figure.number: e for e in doc.elements if e.figure is not None}


def test_page_labels_and_count(doc: ParsedDocument) -> None:
    assert doc.page_count == 3
    labels = {e.page.idx: e.page.label for e in doc.elements}
    assert labels == {0: "1-1", 1: "1-2", 2: "1-3"}


def test_heading_hierarchy_in_section_path(doc: ParsedDocument) -> None:
    by_text = {e.text[:12]: e for e in doc.elements if e.kind == "text" and e.page.idx < 2}
    assert by_text["Lift is prod"].section_path == (CHAPTER, "Principles of Lift")
    # A new section replaces the previous one but keeps the chapter.
    assert by_text["The airspeed"].page.idx == 1
    assert by_text["The airspeed"].section_path == (CHAPTER, "Stability and Control")
    # A subsection nests under the current section (page 2).
    last = [e for e in doc.elements if e.page.idx == 2 and e.kind == "text"][0]
    assert last.section_path == (CHAPTER, "Stability and Control", "Airspeed Indications")


def test_headings_are_not_emitted_as_body_text(doc: ParsedDocument) -> None:
    texts = [e.text for e in doc.elements if e.kind == "text"]
    assert not any(t.strip() == "Principles of Lift" for t in texts)


def test_both_figures_found_with_captions(doc: ParsedDocument) -> None:
    figs = _figures(doc)
    assert set(figs) == {"1-1", "1-2"}
    f1, f2 = figs["1-1"].figure, figs["1-2"].figure
    assert f1 is not None and f2 is not None
    assert f1.caption == "Figure 1-1. Lift versus angle of attack."
    assert figs["1-1"].text == f1.caption
    assert f2.caption.startswith("Figure 1-2.")
    assert figs["1-1"].page.idx == 0 and figs["1-2"].page.idx == 1
    assert figs["1-1"].section_path == (CHAPTER, "Principles of Lift")


def test_vector_vs_raster(doc: ParsedDocument) -> None:
    figs = _figures(doc)
    assert figs["1-1"].figure is not None and figs["1-1"].figure.is_vector is True
    assert figs["1-2"].figure is not None and figs["1-2"].figure.is_vector is False


@pytest.mark.parametrize("number,caption_y", [("1-1", 545), ("1-2", 405)])
def test_figure_png_is_valid_and_cropped_to_the_drawing(
    doc: ParsedDocument, number: str, caption_y: int
) -> None:
    fig = _figures(doc)[number].figure
    assert fig is not None
    assert _png_size(fig.png) == (fig.width, fig.height)
    assert fig.bbox is not None
    x0, y0, x1, y1 = fig.bbox
    # The region covers the 300x200 pt drawing (plus padding) but not the whole page.
    assert 300 <= x1 - x0 < 400 and 200 <= y1 - y0 < 300
    # It must stop above the caption and start below the body text.
    assert y0 > 150 and y1 <= caption_y
    assert 200 < fig.width < 1500 and 200 < fig.height < 1500
    assert len(fig.png) < 500_000


def test_decorative_tiny_image_is_dropped(doc: ParsedDocument) -> None:
    # Exactly two figures: the 20x20 px image on page 1 produced nothing.
    assert len([e for e in doc.elements if e.kind == "figure"]) == 2


def test_body_text_present_and_furniture_absent(doc: ParsedDocument) -> None:
    body = " ".join(e.text for e in doc.elements if e.kind == "text")
    assert "Lift is produced by the wings" in body
    assert "Static stability is the initial tendency" in body
    assert mini.HEADER_TEXT not in body
    assert not re.search(r"\b1-[123]\b", body)  # footer labels
    assert mini.VECTOR_LABEL not in body  # text inside a figure belongs to the figure


def test_elements_in_reading_order(doc: ParsedDocument) -> None:
    assert [e.page.idx for e in doc.elements] == sorted(e.page.idx for e in doc.elements)
    page0 = [e for e in doc.elements if e.page.idx == 0]
    assert page0[-1].kind == "figure"  # the figure sits below the paragraphs on the page


def test_sha256_is_of_file_bytes(doc: ParsedDocument) -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", doc.sha256)


# ---- Real-chapter regression tests (skipped unless the PDFs are available) ----------------


def _real(name: str) -> Path:
    d = os.environ.get("FAA_PDF_DIR")
    if not d:
        pytest.skip("FAA_PDF_DIR not set; point it at a folder with the PHAK chapter PDFs")
    p = Path(d) / name
    if not p.exists():
        pytest.skip(f"{p} not found")
    return p


@pytest.fixture(scope="module")
def ch8() -> ParsedDocument:
    return HandbookPdfParser().parse(_real("10_phak_ch8.pdf"), SOURCE)


@pytest.fixture(scope="module")
def ch11() -> ParsedDocument:
    return HandbookPdfParser().parse(_real("13_phak_ch11.pdf"), SOURCE)


def _check_chapter(doc: ParsedDocument, chapter: int, n_figs: int) -> dict[str, Element]:
    assert doc.page_count == 28
    pages = {e.page.idx: e.page.label for e in doc.elements}
    assert len(pages) == 28
    assert all(lbl and re.fullmatch(rf"{chapter}-\d+", lbl) for lbl in pages.values())
    figs = {e.figure.number: e for e in doc.elements if e.figure and e.figure.number}
    # Ch. 11's printed caption for Fig 11-31 reads "Figure 10-31" (a typo in the FAA book).
    # Numbers are kept as printed, so that is the string to expect.
    expected = {f"{chapter}-{i}" for i in range(1, n_figs + 1)}
    if chapter == 11:
        expected = expected - {"11-31"} | {"10-31"}
    assert set(figs) == expected
    assert len([e for e in doc.elements if e.figure]) == n_figs  # no duplicates
    for e in figs.values():
        assert e.figure is not None
        assert _png_size(e.figure.png) == (e.figure.width, e.figure.height)
        assert e.figure.is_vector is not None and e.figure.bbox is not None
    return figs


def test_real_ch8(ch8: ParsedDocument) -> None:
    figs = _check_chapter(ch8, 8, 39)
    # Fig 8-38 used to be merged with 8-37 (one crop spanning both).
    a, b = figs["8-37"].figure, figs["8-38"].figure
    assert a and b and a.bbox and b.bbox
    assert a.bbox[3] <= b.bbox[1] + 5 or a.bbox[2] <= b.bbox[0] + 5


def test_real_ch11(ch11: ParsedDocument) -> None:
    figs = _check_chapter(ch11, 11, 34)
    a, b = figs["11-23"].figure, figs["11-24"].figure
    assert a and b and a.bbox and b.bbox
    # 11-24 used to lose its top part to 11-23 because of a short rule line.
    assert a.bbox[3] <= b.bbox[1] + 5 or a.bbox[2] <= b.bbox[0] + 5
    flat = {h for e in ch11.elements for h in e.section_path}
    for n in range(1, 14):
        assert f"Sample Problem {n}" in flat
    assert "Performance Charts" in flat
    assert any("Aircraft Performance" in h for h in flat)


@pytest.mark.parametrize(
    "text, label",
    [
        ("8-22", "8-22"),  # chapter page
        (" 17-3 ", "17-3"),
        ("A-1", "A-1"),  # appendices
        ("G-12", "G-12"),  # glossary
        ("I-3", "I-3"),  # index
        ("iii", "iii"),  # front matter
        ("Left rudder", None),  # a caption line near the bottom is not a label
        ("2026", None),  # nor is a year
        ("Figure 8-22", None),
    ],
)
def test_footer_label_forms(text: str, label: str | None) -> None:
    m = FOOTER_LABEL.match(text)
    assert (m.group(1) if m else None) == label
