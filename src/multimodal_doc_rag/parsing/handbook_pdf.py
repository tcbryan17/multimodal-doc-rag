"""FAA Pilot's Handbook (PDF) parser, built on PyMuPDF (ADR 0006).

A PDF stores positioned text runs and drawing operators, not paragraphs, headings or figures.
So every structural fact here is inferred from geometry and fonts by a small named rule:

  page label     the printed footer ("8-22"), not the PDF page number
  headings       font size + weight (+ one regex for "Sample Problem N")
  reading order  the book is two-column: left column top-to-bottom, then right column
  figures        most are VECTOR drawings (57 of 73 in the spike), so there is no image to
                 extract. We find the region above each "Figure N-M." caption from the
                 drawing clusters and raster placements, then render that region to PNG.
  decoration     chapter-opener art, bullets/logos and repeated page furniture are dropped
  tables         not emitted (see TABLES below)

Every number that was tuned on the real chapters is a named constant at the top, with the
reason next to it.
"""

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

from multimodal_doc_rag.types import Element, Figure, PageRef, ParsedDocument, SourceInfo

# ---- Page furniture -----------------------------------------------------------------------
# The book has no running header, but the footer label sits ~46 pt above the bottom edge
# (y ~ 728 on a 774 pt page). Anything whose top is in the bottom FOOTER_ZONE is footer.
FOOTER_ZONE = 60.0
# Body text starts at y ~ 43, so a line that ends above this is a running header (none in
# the real book; the guard keeps a header from ever becoming a "paragraph").
HEADER_ZONE = 36.0
FOOTER_LABEL = re.compile(r"^\s*(\d+-\d+)\s*$")

# ---- Headings -----------------------------------------------------------------------------
# Measured from the two spike chapters (see probe_headings in the spike branch):
#   Chapter opener   AgencyFB 48 ("Aircraft Performance") and AgencyFB 16 ("Chapter 11")
#   Section          Helvetica-Bold 12
#   Subsection       Helvetica-Bold 10 (short, one line)
#   Sub-subsection   Times-BoldItalic 11, and "Sample Problem N" in Times-Bold 10 (the rule
#                    the spike missed: body font family, bold, but a heading by its text)
# Sizes are compared with a tolerance because PDFs report floats (9.8 is a chart label in
# Helvetica-Bold, not a heading; 10.9 is a gauge reading).
CHAPTER_MIN_SIZE = 16.0
SECTION_SIZE = 12.0
SUBSECTION_SIZE = 10.0
SUBSUBSECTION_SIZE = 11.0
HEADING_SIZE_TOLERANCE = 0.15
SECTION_SIZE_TOLERANCE = 0.5
SUBSECTION_MAX_CHARS = 60  # longer bold lines are run-in emphasis, not headings
MAX_HEADING_SPANS = 2  # a heading line is one style run (two when a trailing space differs)
SAMPLE_PROBLEM = re.compile(r"^Sample Problem \d+\b")
CHAPTER_LABEL = re.compile(r"^Chapter \d+$")

# ---- Reading order ------------------------------------------------------------------------
# A block wider than this fraction of the page spans both columns (a full-width figure
# caption, say). It splits the page into bands that are read top to bottom.
FULL_WIDTH_FRACTION = 0.6
# Column test: a block starting left of (middle - slack) is in the left column. Odd pages
# indent the left column to x = 72 and right to 321; even pages use 36 and 285. The slack
# keeps the 285 right column on the right of a 297 midpoint.
COLUMN_SLACK = 20.0

# ---- Figures ------------------------------------------------------------------------------
CAPTION = re.compile(r"^\s*Figure\s+(\d+-\d+)\.")
# Captions are bold (Helvetica-Bold 8). Body references like "Figure 11-8 provides..." are
# in italics and have no period after the number, but the bold check is the safeguard.
CONTAINED_FRACTION = 0.8  # an item this far inside a bigger one is part of it
FRAME_AREA_FRACTION = 0.5  # a single drawing covering this much of the page is a frame
MIN_REGION_SIDE = 20.0  # drawing clusters / images smaller than this are bullets or rules
RULE_MAX_HEIGHT = 3.0  # a full-width line this thin is a page rule, not part of a figure
RULE_MIN_WIDTH = 400.0
# A region reaches up to the lowest body paragraph above the caption. A one-line "paragraph"
# might be a callout label, so only multi-line Times-Roman 10 blocks count as body.
BODY_FONT_PREFIX = "Times-Roman"
BODY_SIZE = 10.0
BODY_MIN_LINES = 2
# Slack when comparing positions: drawings often end a hair under the caption's top edge.
CAPTION_SLACK = 4.0
CEILING_SLACK = 2.0
REGION_PADDING = 3.0  # so strokes at the edge of the drawing aren't clipped
FULL_WIDTH_CAPTION = 330.0  # caption wider than this: figure spans the page, else its column
PAGE_MARGIN = 36.0
# Decorative-image rules (ADR 0008, "the free rules"):
MIN_IMAGE_PX = 50  # under 50 px in either dimension: a bullet or logo
FULL_PAGE_WIDTH_FRACTION = 0.95  # chapter-opener art covers the page
REPEATED_IMAGE_MIN_PAGES = 5  # the same image on this many pages: page furniture
# Share of the region covered by one big embedded image above which the figure is "raster".
RASTER_COVERAGE = 0.5
BIG_IMAGE_SIDE = 60.0
# Rendering resolution. Vision models downscale to roughly 1500 px on the long side, so
# more pixels are wasted. At 130 dpi a full-width figure (520 pt) is ~940 px and a full-page
# one (700 pt) ~1260 px, both under that limit, while 7 pt callout text is ~12 px tall: legible.
# 110 dpi (the spike) made small axis labels borderline; 200 dpi would only grow the PNGs.
RENDER_DPI = 130

# ---- TABLES -------------------------------------------------------------------------------
# Decision: the parser does NOT emit table elements for this handbook. Measured with
# page.find_tables() on Ch. 8 and Ch. 11: every Ch. 11 hit (6) lies inside a figure region (the
# performance tables such as Fig 11-24 are printed as figures, and are rendered as PNG for the
# vision model), so a Markdown table would only duplicate the figure. All 3 Ch. 8 hits are
# worked arithmetic lines in body text ("29.94 - 29.69 = 0.25") turned into garbled 2-column
# tables, which is worse than the plain text we already emit. Revisit if the eval shows table
# questions failing or other chapters contain true tables.


@dataclass(frozen=True)
class _Line:
    rect: pymupdf.Rect
    text: str
    font: str
    size: float
    n_spans: int
    block: int  # index of the PDF text block this line belongs to


@dataclass(frozen=True)
class _Block:
    index: int
    rect: pymupdf.Rect
    lines: tuple[_Line, ...]

    @property
    def text(self) -> str:
        return " ".join(ln.text for ln in self.lines)


def _is_bold(font: str) -> bool:
    return "Bold" in font


def _near(a: float, b: float, tol: float = HEADING_SIZE_TOLERANCE) -> bool:
    return abs(a - b) <= tol


# ---- Rule: page label -----------------------------------------------------------------------


def page_label(blocks: list[_Block], page_height: float) -> str | None:
    """The label printed in the footer, e.g. "8-22". None if the page prints none."""
    for b in blocks:
        if b.rect.y0 > page_height - FOOTER_ZONE:
            m = FOOTER_LABEL.match(b.text)
            if m:
                return m.group(1)
    return None


def _in_furniture(rect: pymupdf.Rect, page_height: float) -> bool:
    return bool(rect.y0 > page_height - FOOTER_ZONE or rect.y1 < HEADER_ZONE)


# ---- Rule: headings -------------------------------------------------------------------------


def heading_level(line: _Line) -> int | None:
    """1 chapter, 2 section, 3 subsection, 4 sub-subsection (or Sample Problem); else None."""
    text = line.text.strip()
    if len(text) < 3 or not any(c.isalpha() for c in text) or line.n_spans > MAX_HEADING_SPANS:
        return None
    if line.size >= CHAPTER_MIN_SIZE:
        return 1
    bold = _is_bold(line.font)
    if (
        bold
        and line.font.startswith("Helvetica")
        and _near(line.size, SECTION_SIZE, SECTION_SIZE_TOLERANCE)
    ):
        return 2
    if bold and line.font.startswith("Helvetica") and _near(line.size, SUBSECTION_SIZE):
        return 3 if len(text) <= SUBSECTION_MAX_CHARS else None
    if line.font == "Times-BoldItalic" and _near(line.size, SUBSUBSECTION_SIZE):
        return 4
    # "Sample Problem N" is set in the BODY family (Times) but bold; the font alone can't
    # separate it from bold run-in emphasis, so the text pattern decides.
    if bold and line.font.startswith("Times") and SAMPLE_PROBLEM.match(text):
        return 4
    return None


# ---- Rule: reading order --------------------------------------------------------------------


def reading_order(blocks: list[_Block], page_width: float) -> list[_Block]:
    """Left column then right column, with full-width blocks as band separators.

    PyMuPDF's native order follows the PDF's drawing order, which for this book puts
    figures before the text beside them. Sorting by y alone would interleave the columns.
    Key = (band, column, y): band counts the full-width blocks above, so a full-width block
    is read after everything above it and before everything below.
    """
    mid = page_width / 2

    def is_full(b: _Block) -> bool:
        return bool(b.rect.width > page_width * FULL_WIDTH_FRACTION)

    fulls = sorted((b for b in blocks if is_full(b)), key=lambda b: b.rect.y0)

    def key(b: _Block) -> tuple[float, int, float]:
        if is_full(b):
            return (fulls.index(b) + 0.5, 0, b.rect.y0)
        above = sum(1 for f in fulls if f.rect.y1 <= b.rect.y0 + 1)
        return (float(above), 0 if b.rect.x0 < mid - COLUMN_SLACK else 1, b.rect.y0)

    return sorted(blocks, key=key)


# ---- Rule: figure regions -------------------------------------------------------------------


@dataclass(frozen=True)
class _Caption:
    number: str
    text: str
    rect: pymupdf.Rect
    block_indexes: tuple[int, ...]  # the caption block and any continuation blocks


def find_captions(ordered: list[_Block], page_height: float) -> list[_Caption]:
    """Blocks starting "Figure N-M." in a bold face; a wrapped caption may span blocks."""
    caps: list[_Caption] = []
    i = 0
    while i < len(ordered):
        b = ordered[i]
        first = b.lines[0]
        m = CAPTION.match(b.text)
        if m and _is_bold(first.font) and not _in_furniture(b.rect, page_height):
            text, rect, used = b.text, pymupdf.Rect(b.rect), [b.index]
            # A caption that wraps can arrive as several blocks of the same face directly
            # below each other; absorb them so the caption isn't truncated.
            while (
                i + 1 < len(ordered)
                and ordered[i + 1].lines[0].font == first.font
                and _near(ordered[i + 1].lines[0].size, first.size, 0.01)
                and 0 <= ordered[i + 1].rect.y0 - rect.y1 < 6
                and not CAPTION.match(ordered[i + 1].text)
            ):
                i += 1
                text += " " + ordered[i].text
                rect |= ordered[i].rect
                used.append(ordered[i].index)
            caps.append(_Caption(m.group(1), " ".join(text.split()), rect, tuple(used)))
        i += 1
    return caps


@dataclass(frozen=True)
class _Item:
    rect: pymupdf.Rect
    is_image: bool


def _visible_drawings(page: pymupdf.Page) -> list[dict[str, Any]]:
    """Drawings with their rectangles cut down to what is actually visible.

    The book builds some figures (Fig 8-16's airspeed tape) from long strips that are drawn
    far off the visible area and masked by a clip rectangle. Plain `get_drawings()` reports the
    unclipped rectangle, so one strip reached the page's footer and `cluster_drawings` merged
    the whole page into one "figure". `extended=True` also reports the clip rectangles and
    nesting levels, so we intersect each drawing with the clips that enclose it.

    Page-sized frames/backgrounds are dropped too, for the same reason.
    """
    page_area = page.rect.get_area()
    clips: dict[int, pymupdf.Rect] = {}  # nesting level -> clip rectangle in force
    visible: list[dict[str, Any]] = []
    for d in page.get_drawings(extended=True):
        level = int(d.get("level", 0))
        for k in [k for k in clips if k >= level]:
            del clips[k]  # a new item at this depth ends deeper clips
        if d["type"] == "clip":
            clips[level] = pymupdf.Rect(d["scissor"])
            continue
        if d["type"] in ("group", "clip-end", "group-end") or "rect" not in d:
            continue
        x0, y0, x1, y1 = d["rect"]
        for clip in clips.values():
            x0, y0, x1, y1 = max(x0, clip.x0), max(y0, clip.y0), min(x1, clip.x1), min(y1, clip.y1)
        if x0 > x1 or y0 > y1:
            continue  # entirely outside its clip: invisible (a zero-width line is still valid)
        rect = pymupdf.Rect(x0, y0, x1, y1)
        if rect.get_area() >= FRAME_AREA_FRACTION * page_area:
            continue
        visible.append({**d, "rect": rect})
    return visible


def figure_candidates(page: pymupdf.Page, repeated_xrefs: set[int]) -> list[_Item]:
    """Drawing clusters and raster placements that could belong to a figure.

    `get_images()` undercounts (it lists only some image objects); `get_image_info()` lists
    every placement with its on-page rectangle, which is what we need.
    """
    items: list[_Item] = []
    page_w = page.rect.width
    drawings = _visible_drawings(page)
    for r in page.cluster_drawings(drawings=drawings):
        rect = pymupdf.Rect(r)
        if rect.height < RULE_MAX_HEIGHT and rect.width > RULE_MIN_WIDTH:
            continue  # a page rule
        items.append(_Item(rect, False))
    for info in page.get_image_info(xrefs=True):
        rect = pymupdf.Rect(info["bbox"])
        if info["width"] < MIN_IMAGE_PX or info["height"] < MIN_IMAGE_PX:
            continue  # bullet / logo
        if rect.width >= page_w * FULL_PAGE_WIDTH_FRACTION:
            continue  # chapter-opener art
        if info.get("xref", 0) in repeated_xrefs:
            continue  # page furniture
        items.append(_Item(rect, True))
    # Full-bleed pictures extend past the page edge (y = -8); clamp so they compare sanely.
    clamped = [_Item(it.rect & page.rect, it.is_image) for it in items]
    return [
        it for it in clamped if it.rect.width > MIN_REGION_SIDE and it.rect.height > MIN_REGION_SIDE
    ]


def assign_owners(items: list[_Item], captions: list[_Caption]) -> dict[str, list[_Item]]:
    """Give each item to one caption, by caption number.

    Rule 1: an item belongs to the nearest caption below it that shares horizontal space. That
    stops a right-column figure reaching up into a full-width picture whose (left-column)
    caption sits lower down: Fig 8-38 swallowed Fig 8-37 that way.
    Rule 2: an item mostly inside a bigger item goes with the bigger one. Fig 8-37's labels
    and arrows are drawings laid over its photo; they would otherwise be handed to whichever
    caption they happen to overlap in x.
    Items are visited biggest first so rule 2 can look at already-assigned bigger items.
    """
    owned: dict[str, list[_Item]] = {c.number: [] for c in captions}
    placed: list[tuple[_Item, _Caption]] = []
    for it in sorted(items, key=lambda i: i.rect.get_area(), reverse=True):
        owner: _Caption | None = None
        for big, big_owner in placed:
            inside = (it.rect & big.rect).get_area()
            if it.rect.get_area() > 0 and inside / it.rect.get_area() >= CONTAINED_FRACTION:
                owner = big_owner
                break
        if owner is None:
            best_gap = float("inf")
            for c in captions:
                gap = c.rect.y0 - it.rect.y1
                shares_x = it.rect.x1 > c.rect.x0 - 2 and it.rect.x0 < c.rect.x1 + 2
                wide = c.rect.width > FULL_WIDTH_CAPTION  # a full-width caption owns the width
                if gap >= -CAPTION_SLACK and (shares_x or wide) and gap < best_gap:
                    owner, best_gap = c, gap
        if owner is not None:
            placed.append((it, owner))
            owned[owner.number].append(it)
    return owned


def figure_region(
    page: pymupdf.Page,
    caption: _Caption,
    other_captions: list[_Caption],
    ordered: list[_Block],
    items: list[_Item],  # only the items assigned to this caption (see assign_owners)
) -> tuple[pymupdf.Rect, bool] | None:
    """The page rectangle holding the figure above `caption`, and whether it is vector.

    1. Pick the column: the page width for a wide caption, else the caption's own column.
    2. The ceiling is the bottom of the lowest multi-line body paragraph above the caption in
       that column, or of another figure's caption above it (this is what keeps adjacent
       figures apart).
    3. Take every drawing cluster / raster between ceiling and caption that overlaps the
       column and union them.
    4. Grow the union to take in callout/axis labels that touch it (small non-body text).
    """
    cap = caption.rect
    cols = (
        (PAGE_MARGIN, page.rect.width - PAGE_MARGIN)
        if cap.width > FULL_WIDTH_CAPTION
        else (cap.x0 - 2, cap.x1 + 2)
    )

    def in_column(r: pymupdf.Rect) -> bool:
        return bool(r.x1 > cols[0] and r.x0 < cols[1])

    ceiling = 0.0
    for b in ordered:
        first = b.lines[0]
        is_body = (
            first.font.startswith(BODY_FONT_PREFIX)
            and _near(first.size, BODY_SIZE, 0.5)
            and len(b.lines) >= BODY_MIN_LINES
        )
        if is_body and b.rect.y1 <= cap.y0 and in_column(b.rect):
            ceiling = max(ceiling, b.rect.y1)
    for other in other_captions:
        if other.rect.y1 <= cap.y0 - 1 and in_column(other.rect):
            ceiling = max(ceiling, other.rect.y1)

    chosen = [
        it
        for it in items
        if it.rect.y1 <= cap.y0 + CAPTION_SLACK
        and it.rect.y0 >= ceiling - CEILING_SLACK
        and in_column(it.rect)
    ]
    if not chosen:
        return None
    region = pymupdf.Rect(chosen[0].rect)
    for it in chosen:
        region |= it.rect
    cap_ids = {i for c in [caption, *other_captions] for i in c.block_indexes}
    for b in ordered:
        first = b.lines[0]
        small_text = not (
            first.font.startswith(BODY_FONT_PREFIX) and _near(first.size, BODY_SIZE, 0.5)
        )
        if (
            small_text
            and b.index not in cap_ids
            and b.rect.intersects(region)
            and b.rect.y1 <= cap.y0 + 2
        ):
            region |= b.rect
    region = (
        region + (-REGION_PADDING, -REGION_PADDING, REGION_PADDING, REGION_PADDING)
    ) & page.rect
    # The biggest single embedded image, not a sum: the book stacks several copies of the same
    # bitmap at slightly different sizes (Fig 8-24), which a sum would count repeatedly and
    # wrongly call a mosaic of vector cards "raster".
    biggest = max(
        (
            it.rect.get_area()
            for it in chosen
            if it.is_image and it.rect.width > BIG_IMAGE_SIDE and it.rect.height > BIG_IMAGE_SIDE
        ),
        default=0.0,
    )
    covered = biggest / max(region.get_area(), 1.0)
    return region, covered <= RASTER_COVERAGE


# ---- Parser ---------------------------------------------------------------------------------


def _read_blocks(page: pymupdf.Page) -> list[_Block]:
    blocks: list[_Block] = []
    d: dict[str, Any] = page.get_text("dict")
    for bi, b in enumerate(d["blocks"]):
        if b["type"] != 0:
            continue
        lines = []
        for ln in b["lines"]:
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            lines.append(
                _Line(
                    rect=pymupdf.Rect(ln["bbox"]),
                    text="".join(s["text"] for s in ln["spans"]).strip(),
                    font=spans[0]["font"],
                    size=float(spans[0]["size"]),
                    n_spans=len(spans),
                    block=bi,
                )
            )
        if lines:
            blocks.append(_Block(bi, pymupdf.Rect(b["bbox"]), tuple(lines)))
    return blocks


def _repeated_image_xrefs(doc: pymupdf.Document) -> set[int]:
    pages_by_xref: dict[int, set[int]] = defaultdict(set)
    for page in doc:
        for info in page.get_image_info(xrefs=True):
            if info.get("xref", 0):
                pages_by_xref[info["xref"]].add(page.number)
    return {x for x, pages in pages_by_xref.items() if len(pages) >= REPEATED_IMAGE_MIN_PAGES}


class HandbookPdfParser:
    """Implements protocols.Parser for the FAA handbook (and chapters of it)."""

    def parse(self, path: Path, source: SourceInfo) -> ParsedDocument:
        data = path.read_bytes()
        doc = pymupdf.open(stream=data, filetype="pdf")
        repeated = _repeated_image_xrefs(doc)
        # The heading stack persists across pages: a section runs until the next heading.
        headings: dict[int, str] = {}
        elements: list[Element] = []
        for page in doc:
            elements.extend(self._parse_page(page, repeated, headings))
        return ParsedDocument(
            source=source,
            sha256=hashlib.sha256(data).hexdigest(),
            page_count=len(doc),
            elements=tuple(elements),
        )

    def _parse_page(
        self, page: pymupdf.Page, repeated: set[int], headings: dict[int, str]
    ) -> Iterator[Element]:
        height = page.rect.height
        blocks = [b for b in _read_blocks(page) if not _in_furniture(b.rect, height)]
        label = page_label(_read_blocks(page), height)
        pref = PageRef(idx=page.number, label=label)
        ordered = reading_order(blocks, page.rect.width)
        captions = find_captions(ordered, height)

        # Figures first: their regions tell us which text lines belong inside a figure.
        items = figure_candidates(page, repeated)
        owned = assign_owners(items, captions)
        figures: dict[int, tuple[_Caption, pymupdf.Rect, bool]] = {}  # first block idx -> ...
        for cap in captions:
            others = [c for c in captions if c is not cap]
            found = figure_region(page, cap, others, ordered, owned[cap.number])
            if found:
                figures[cap.block_indexes[0]] = (cap, found[0], found[1])
        regions = [r for _, r, _ in figures.values()]
        caption_blocks = {i for c in captions for i in c.block_indexes}

        paragraph: list[str] = []

        def path() -> tuple[str, ...]:
            return tuple(headings[k] for k in sorted(headings))

        def flush() -> Iterator[Element]:
            if paragraph:
                text = " ".join(" ".join(paragraph).split())
                paragraph.clear()
                if text:
                    yield Element("text", text, pref, path())

        pending: tuple[int, str, int] | None = None  # (level, text, block) heading being built

        def commit_heading() -> None:
            nonlocal pending
            if pending:
                level, text, _ = pending
                for k in [k for k in headings if k >= level]:
                    del headings[k]
                headings[level] = text
                pending = None

        caption_first = {c.block_indexes[0]: c for c in captions}
        for b in ordered:
            if b.index in caption_blocks:
                commit_heading()
                yield from flush()
                first_of = caption_first.get(b.index)
                if first_of is None:
                    continue  # continuation block of a caption, already merged into it
                if b.index in figures:
                    _, region, is_vector = figures[b.index]
                    yield self._figure_element(page, first_of, region, is_vector, pref, path())
                else:
                    # No drawing found above the caption: keep the caption as plain text so
                    # the sentence is still searchable, rather than dropping it.
                    yield Element("text", first_of.text, pref, path())
                continue
            for ln in b.lines:
                if any(_overlap_fraction(ln.rect, r) > 0.5 for r in regions):
                    continue  # text inside a figure belongs to the figure
                level = heading_level(ln)
                if level is None:
                    commit_heading()
                    paragraph.append(ln.text)
                    continue
                yield from flush()
                if pending and pending[0] == level and (pending[2] == b.index or level == 1):
                    # A heading that wraps onto a second line (or "Chapter 11" above the
                    # chapter title) is one heading.
                    joiner = ": " if CHAPTER_LABEL.match(pending[1]) else " "
                    pending = (level, pending[1] + joiner + ln.text, b.index)
                else:
                    commit_heading()
                    pending = (level, ln.text, b.index)
            yield from flush()  # a PDF block is a paragraph; never merge across blocks
        commit_heading()
        yield from flush()

    def _figure_element(
        self,
        page: pymupdf.Page,
        cap: _Caption,
        region: pymupdf.Rect,
        is_vector: bool,
        pref: PageRef,
        section: tuple[str, ...],
    ) -> Element:
        pix = page.get_pixmap(clip=region, dpi=RENDER_DPI)
        figure = Figure(
            number=cap.number,
            caption=cap.text,
            png=pix.tobytes("png"),
            width=pix.width,
            height=pix.height,
            bbox=(region.x0, region.y0, region.x1, region.y1),
            is_vector=is_vector,
        )
        return Element("figure", cap.text, pref, section, figure)


def _overlap_fraction(line: pymupdf.Rect, region: pymupdf.Rect) -> float:
    """Share of the line's area that lies inside the region."""
    inter = line & region
    area = line.get_area()
    return inter.get_area() / area if area > 0 and not inter.is_empty else 0.0
