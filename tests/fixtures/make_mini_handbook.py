"""Builds a tiny 3-page handbook-like PDF at test time, so no PDF binary is committed.

It mimics the layout facts the parser's rules depend on (see parsing/handbook_pdf.py):
big bold chapter title, Helvetica-Bold 12 section headings, Times-Roman 10 body, a vector
figure (drawn lines and rectangles, no image object), a raster figure (embedded PNG), a tiny
decorative image, a running header, and a printed footer label ("1-1", "1-2", "1-3").
"""

from pathlib import Path

import pymupdf

PAGE_W, PAGE_H = 612, 792
LEFT, RIGHT = 72, 540

HEADER_TEXT = "RUNNING HEADER SHOULD NOT APPEAR"
VECTOR_LABEL = "Callout inside vector drawing"

PARAGRAPH_A = (
    "Lift is produced by the wings as air flows over and under them. The amount of lift "
    "depends on the angle of attack, the airspeed and the air density. Pilots manage these "
    "factors with the controls throughout every phase of flight."
)
PARAGRAPH_B = (
    "Stability describes how an aircraft returns to its trimmed condition after a "
    "disturbance. Static stability is the initial tendency; dynamic stability is how the "
    "motion develops over time. Both matter for safe handling."
)
PARAGRAPH_C = (
    "The airspeed indicator reads dynamic pressure. Errors arise from position and "
    "instrument faults, so the pilot must know the limits of each reading."
)


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), False)
    pix.set_rect(pix.irect, rgb)
    return bytes(pix.tobytes("png"))


def _footer(page: pymupdf.Page, label: str) -> None:
    # Odd/even pages print the label at the right/left in the real book; position is
    # irrelevant to the parser, only "near the bottom" and the n-m shape matter.
    page.insert_text((540, 765), label, fontname="helv", fontsize=10)


def _header(page: pymupdf.Page) -> None:
    page.insert_text((LEFT, 24), HEADER_TEXT, fontname="helv", fontsize=8)


def _para(page: pymupdf.Page, y: float, text: str) -> None:
    page.insert_textbox(pymupdf.Rect(LEFT, y, RIGHT, y + 70), text, fontname="tiro", fontsize=10)


def build(path: Path) -> None:
    doc = pymupdf.open()

    # Page 0: chapter title, section, two paragraphs, vector figure 1-1.
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    _header(p)
    p.insert_text((LEFT, 90), "Aerodynamics of Flight", fontname="hebo", fontsize=24)
    p.insert_text((LEFT, 130), "Principles of Lift", fontname="hebo", fontsize=12)
    _para(p, 140, PARAGRAPH_A)
    _para(p, 215, PARAGRAPH_B)
    # Vector figure: a box, an axis and a diagonal line. No image object is involved.
    p.draw_rect(pymupdf.Rect(150, 320, 450, 520), color=(0, 0, 0), width=1.5)
    p.draw_line((150, 520), (450, 320), color=(0.8, 0, 0), width=2)
    p.draw_line((300, 320), (300, 520), color=(0, 0, 0.8), width=1)
    p.draw_rect(pymupdf.Rect(200, 380, 260, 430), color=(0, 0.5, 0), fill=(0.8, 1, 0.8))
    p.insert_text((310, 350), VECTOR_LABEL, fontname="helv", fontsize=7)
    p.insert_text(
        (LEFT, 545), "Figure 1-1. Lift versus angle of attack.", fontname="hebo", fontsize=8
    )
    _footer(p, "1-1")

    # Page 1: section, raster figure 1-2, tiny decorative image.
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    _header(p)
    p.insert_text((LEFT, 80), "Stability and Control", fontname="hebo", fontsize=12)
    _para(p, 90, PARAGRAPH_C)
    p.insert_image(pymupdf.Rect(150, 180, 450, 380), stream=_png(300, 200, (90, 140, 200)))
    p.insert_text(
        (LEFT, 405), "Figure 1-2. A photograph of a cockpit panel.", fontname="hebo", fontsize=8
    )
    # A 20x20 pixel image (under the 50 px floor): a bullet or logo, not a figure.
    p.insert_image(pymupdf.Rect(480, 60, 500, 80), stream=_png(20, 20, (200, 0, 0)))
    _footer(p, "1-2")

    # Page 2: a subsection under the section, more body text.
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    _header(p)
    p.insert_text((LEFT, 80), "Airspeed Indications", fontname="hebo", fontsize=10)
    _para(p, 90, PARAGRAPH_C)
    _footer(p, "1-3")

    doc.save(path)
    doc.close()
