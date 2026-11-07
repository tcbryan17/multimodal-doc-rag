"""EDGAR 10-K HTML parser (ADR 0006): hand-rolled BeautifulSoup + lxml.

An EDGAR filing is one long HTML file with no real "pages". The printed pages survive only as
(1) CSS page-break hints (`page-break-before/after: always`) and (2) a page number typed into
a footer line. We rebuild pages from the first and labels from the second.

Pipeline: HTML -> flat list of blocks (text lines, tables, page breaks) -> pages -> elements.
"""

import hashlib
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning
from bs4.element import NavigableString

from multimodal_doc_rag.types import Element, ElementKind, PageRef, ParsedDocument, SourceInfo

_BREAK_BEFORE = re.compile(r"page-break-before\s*:\s*always|break-before\s*:\s*page", re.I)
_BREAK_AFTER = re.compile(r"page-break-after\s*:\s*always|break-after\s*:\s*page", re.I)
_HIDDEN = re.compile(r"display\s*:\s*none", re.I)
_BOLD_STYLE = re.compile(r"font-weight\s*:\s*(bold|[6-9]00)", re.I)
# Tags that make a node a container (recurse into it) rather than a single line of text.
_BLOCKS = ("div", "p", "table", "hr", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6")

# A footer is only a page number: "23", "F-7", "Page 4", or a roman numeral "ii".
# Limited to 1-3 digits so a stray year ("2024") is never taken for a page number.
_FOOTER = re.compile(r"(?:page\s+)?(?:[A-Z]-)?\d{1,3}|[ivxl]{1,6}", re.I)
# Item headings come as "Item 1A. Risk Factors" (Apple, J&J, MSFT) or "Item 1A—Risk Factors"
# (Costco: em/en dash or hyphen, no period), so accept any of those separators after the number.
_ITEM = re.compile(r"Item\s+\d{1,2}[A-C]?\s*[.\u2014\u2013-]", re.I)
_PART = re.compile(r"PART\s+[IV]+\.?", re.I)
# Real headings are short; this keeps body text citing "Item 7." out. 200 (not 120) because
# Costco's Item 7 line is "Item 7—Management's Discussion ... Operations (amounts in millions,
# except per share ... data)": the title plus a long non-bold parenthetical in the same <div>.
_MAX_HEADING_LEN = 200
# MSFT opens every page with a running header "PART II" + "Item 8" (or "Item 2, 3, 4"): same
# words as a heading but with no separator or title. It must not act as a heading, or the PART
# line would end the current Item on every page.
_RUNNING_ITEM = re.compile(r"Items?\s+\d{1,2}[A-C]?(?:\s*,\s*\d{1,2}[A-C]?)*", re.I)
_MAX_SUBHEADING_LEN = 80

# A running footer that carries a document name next to the number, written either as one line
# ("Apple Inc. | 2026 Form 10-K | 23") or as a one-row table ("2025 Annual Report" | "43", J&J).
# Requiring "10-K" / "Annual Report" in the text is what keeps a genuine two-cell data table
# ("Net sales | 12") that happens to end a page from being mistaken for a footer.
_RUNNING_FOOTER = re.compile(
    r"(?:[^|]{1,60}\|\s*)?[^|]*(?:10-K|annual\s+report)[^|]*\|\s*(?:[A-Z]-)?\d{1,3}", re.I
)
# Costco repeats a "Table of Contents" back-link at the top of every page; it is navigation.
_NAV_LINE = re.compile(r"table of contents", re.I)

_PREFIX_CELLS = {"$", "(", "$("}  # glued onto the number to their right
_SUFFIX_CELLS = {")", "%", ")%"}  # glued onto the number to their left


@dataclass(frozen=True)
class _Line:
    text: str
    bold: bool


@dataclass(frozen=True)
class _Table:
    markdown: str


class _Break:
    """Marker for a page break in the flat block stream."""


_BREAK = _Break()
_Block = _Line | _Table | _Break


def _norm(text: str) -> str:
    """Replace nbsp and collapse all whitespace runs (EDGAR text is full of both)."""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _style(tag: Tag) -> str:
    value = tag.get("style")
    return value if isinstance(value, str) else ""


def _is_hidden(tag: Tag) -> bool:
    # ix:header holds inline-XBRL metadata that is never shown on the page.
    return tag.name == "ix:header" or bool(_HIDDEN.search(_style(tag)))


def _is_bold(tag: Tag) -> bool:
    """True if every visible character of the line sits inside bold markup."""
    saw_text = False
    for s in tag.find_all(string=True):
        if not isinstance(s, NavigableString) or not _norm(str(s)):
            continue
        saw_text = True
        node: Tag | None = s.parent
        bold = False
        while node is not None:
            if node.name in ("b", "strong") or _BOLD_STYLE.search(_style(node)):
                bold = True
                break
            if node is tag:
                break
            node = node.parent
        if not bold:
            return False
    return saw_text


def _grid(table: Tag) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        row: list[str] = []
        for td in tr.find_all(["td", "th"]):
            row.append(_norm(td.get_text()))
            span = td.get("colspan")
            # A colspan cell occupies several columns; pad so columns stay aligned.
            if isinstance(span, str) and span.isdigit():
                row.extend([""] * (int(span) - 1))
        rows.append(row)
    return rows


def _merge_row(row: list[str]) -> list[str]:
    """Glue "$" / "(" onto the next value and ")" / "%" onto the previous one.

    The merged text stays at the *first* column of the cluster, which is also where a
    colspan header cell puts its text, so headers and values still line up.
    """
    row = row[:]
    for i in range(len(row) - 1, -1, -1):  # right to left so "$" + "(" + "1" nests properly
        if row[i] in _PREFIX_CELLS:
            nxt = next((j for j in range(i + 1, len(row)) if row[j]), None)
            if nxt is not None:
                row[i] += row[nxt]
                row[nxt] = ""
    for i in range(len(row)):
        if row[i] in _SUFFIX_CELLS:
            prev = next((j for j in range(i - 1, -1, -1) if row[j]), None)
            if prev is not None:
                row[prev] += row[i]
                row[i] = ""
    return row


def _table_block(table: Tag) -> _Line | _Table | None:
    grid = [_merge_row(r) for r in _grid(table)]
    grid = [r for r in grid if any(r)]
    if not grid:
        return None
    cells = [c for r in grid for c in r if c]
    if len(grid) == 1 and _RUNNING_FOOTER.fullmatch(" | ".join(cells)):
        # Footer laid out as a table. Emit it as a line so the page logic treats it like any
        # other footer (it is then stripped and its trailing number becomes the label).
        return _Line(" | ".join(cells), False)
    if len(cells) == 1:
        # Layout-only table (a single cell used for positioning): treat it as plain text.
        text = next(c for r in grid for c in r if c)
        return _Line(text, _is_bold(table))
    width = max(len(r) for r in grid)
    grid = [r + [""] * (width - len(r)) for r in grid]
    keep = [c for c in range(width) if any(r[c] for r in grid)]  # drop spacer columns
    rows = [[r[c].replace("|", "\\|") for c in keep] for r in grid]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * len(keep)]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return _Table("\n".join(lines))


def _walk(node: Tag, out: list[_Block]) -> None:
    for child in node.children:
        if not isinstance(child, Tag) or _is_hidden(child):
            continue
        style = _style(child)
        if _BREAK_BEFORE.search(style):
            out.append(_BREAK)
        if child.name == "table":
            block = _table_block(child)
            if block is not None:
                out.append(block)
        elif child.name == "hr":
            pass  # only a separator; its page-break style was handled above
        elif child.find(_BLOCKS) is not None:
            _walk(child, out)
        else:
            for br in child.find_all("br"):
                br.replace_with(" ")
            text = _norm(child.get_text())
            if text:
                out.append(_Line(text, _is_bold(child)))
        if _BREAK_AFTER.search(style):
            out.append(_BREAK)


def _footer_label(text: str) -> str | None:
    """The printed page label if this line is a page footer, else None."""
    if _FOOTER.fullmatch(text):
        return re.sub(r"(?i)^page\s+", "", text)
    if _RUNNING_FOOTER.fullmatch(text):
        return text.rsplit("|", 1)[1].strip()
    return None


def _split_pages(blocks: list[_Block]) -> list[list[_Line | _Table]]:
    pages: list[list[_Line | _Table]] = [[]]
    for b in blocks:
        if isinstance(b, _Break):
            if pages[-1]:  # consecutive/leading breaks must not create empty pages
                pages.append([])
        else:
            pages[-1].append(b)
    return [p for p in pages if p]


class EdgarHtmlParser:
    """Implements protocols.Parser for EDGAR 10-K HTML."""

    def parse(self, path: Path, source: SourceInfo) -> ParsedDocument:
        raw = path.read_bytes()
        with warnings.catch_warnings():
            # Expected: 10-Ks are inline XBRL, i.e. XHTML, so they start with "<?xml". We still
            # want the lenient lxml *HTML* parser (it copes with the sloppy markup and keeps
            # the ix: tags as plain tags), so the warning telling us to use an XML parser is noise.
            warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
            soup = BeautifulSoup(raw, "lxml")
        body = soup.body or soup
        blocks: list[_Block] = []
        _walk(body, blocks)
        pages = _split_pages(blocks)
        if not pages:
            raise ValueError(f"no content found in {path}")

        elements: list[Element] = []
        item: str | None = None
        sub: str | None = None
        for idx, page in enumerate(pages):
            label: str | None = None
            last = page[-1]
            footer = _footer_label(last.text) if isinstance(last, _Line) else None
            if footer is not None:
                # Footer = last line on the page that is a page number (bare or with a
                # document name). It's the page's printed label, not content, so it's dropped.
                label = footer
                page = page[:-1]
            if (
                len(page) > 2
                and isinstance(page[0], _Line)
                and isinstance(page[1], _Line)
                and _PART.fullmatch(page[0].text)
                and _RUNNING_ITEM.fullmatch(page[1].text)
            ):
                page = page[2:]
            if page and isinstance(page[0], _Line) and _NAV_LINE.fullmatch(page[0].text):
                page = page[1:]
            ref = PageRef(idx=idx, label=label)
            for b in page:
                kind: ElementKind
                if isinstance(b, _Table):
                    kind, text = "table", b.markdown
                elif _PART.fullmatch(b.text):
                    # PART headings are not part of the path (Items are unique on their own,
                    # and the path stays short for context headers) but they do end the
                    # previous Item, so text after "PART II" isn't filed under Item 4.
                    item = sub = None
                    continue
                elif len(b.text) <= _MAX_HEADING_LEN and _ITEM.match(b.text):
                    item, sub = b.text, None
                    continue
                elif (
                    item is not None
                    and b.bold
                    and len(b.text) <= _MAX_SUBHEADING_LEN
                    and not b.text.endswith(".")
                ):
                    sub = b.text
                    continue
                else:
                    kind, text = "text", b.text
                section = tuple(s for s in (item, sub) if s)
                elements.append(Element(kind=kind, text=text, page=ref, section_path=section))
        return ParsedDocument(
            source=source,
            sha256=hashlib.sha256(raw).hexdigest(),
            page_count=len(pages),
            elements=tuple(elements),
        )
