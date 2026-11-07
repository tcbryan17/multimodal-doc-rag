"""Structure-aware chunker (ADR 0007). Pure functions, no I/O.

A chunk is the unit we embed, retrieve and cite, so the rules aim for "one chunk is about
one thing and sits on a known page range": sections, tables and figures are never mixed.
"""

import math
import re

from multimodal_doc_rag.types import Chunk, Element, PageRef, ParsedDocument

# Sentence boundary: whitespace after . ! or ?. Known limits: it also splits after
# abbreviations ("Dr. Smith", "e.g. this") and decimals followed by a space; it misses
# sentences ending in a closing quote/bracket. Over-splitting only makes a piece slightly
# smaller, so a simple regex is acceptable for this fallback path.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def count_tokens(text: str) -> int:
    """Approximate token count as ceil(chars / 4).

    An approximation is fine: chunk size is a tuned setting (the eval compares 256/512/1024),
    and every model's tokenizer counts differently anyway, so exactness would be false precision.
    """
    return math.ceil(len(text) / 4)


def context_header(doc_title: str, section_path: tuple[str, ...]) -> str:
    """'<doc title> › <s1> › <s2>', or just the title when there is no section path."""
    return " › ".join((doc_title, *section_path))


def _hard_split(text: str, max_tokens: int) -> list[str]:
    """Last resort: cut a run with no sentence boundary every max_tokens*4 characters."""
    width = max_tokens * 4
    return [text[i : i + width] for i in range(0, len(text), width)]


def _split_paragraph(text: str, max_tokens: int) -> list[str]:
    """Split an oversized paragraph into pieces of <= max_tokens, at sentence boundaries."""
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        for part in _hard_split(sentence, max_tokens):  # no-op unless sentence is too big
            candidate = f"{current} {part}" if current else part
            if current and count_tokens(candidate) > max_tokens:
                pieces.append(current)
                current = part
            else:
                current = candidate
    if current:
        pieces.append(current)
    return pieces


def _split_table(text: str, max_tokens: int) -> list[str]:
    """Split a Markdown table by rows; every piece repeats the header row and separator line.

    A single row bigger than the budget is kept whole rather than cut mid-cell (a broken row
    is worse than an oversized one), as is a table too short to have a header to repeat.
    """
    lines = text.splitlines()
    if count_tokens(text) <= max_tokens or len(lines) <= 3:
        return [text]
    header = "\n".join(lines[:2])
    pieces: list[str] = []
    rows: list[str] = []
    for row in lines[2:]:
        candidate = "\n".join([header, *rows, row])
        if rows and count_tokens(candidate) > max_tokens:
            pieces.append("\n".join([header, *rows]))
            rows = [row]
        else:
            rows.append(row)
    if rows:
        pieces.append("\n".join([header, *rows]))
    return pieces


def _figure_content(el: Element) -> str:
    """Caption text for now; an ingest step later prepends the vision description."""
    text = el.text.strip()
    if text:
        return text
    # An uncaptioned figure must still yield non-empty content (no empty chunks).
    assert el.figure is not None
    number = el.figure.number
    return f"Figure {number}" if number else "Figure"


def chunk_document(doc: ParsedDocument, *, max_tokens: int = 500) -> list[Chunk]:
    """Chunk a parsed document in reading order. See ADR 0007 for the rules."""
    if max_tokens < 1:
        raise ValueError(f"max_tokens must be >= 1, got {max_tokens}")

    chunks: list[Chunk] = []
    title = doc.source.title

    def emit(
        element: Element,
        content: str,
        start: PageRef,
        end: PageRef,
    ) -> None:
        chunks.append(
            Chunk(
                ordinal=len(chunks),
                kind=element.kind,
                section_path=element.section_path,
                page_start=start,
                page_end=end,
                content=content,
                context_header=context_header(title, element.section_path),
                figure=element.figure,
                informational=None,
            )
        )

    buffer: list[Element] = []

    def flush() -> None:
        if buffer:
            content = "\n\n".join(e.text.strip() for e in buffer)
            emit(buffer[0], content, buffer[0].page, buffer[-1].page)
            buffer.clear()

    for el in doc.elements:
        if el.kind == "text":
            text = el.text.strip()
            if buffer and buffer[0].section_path != el.section_path:
                flush()  # a section change always starts a new chunk
            if count_tokens(text) > max_tokens:
                flush()
                for piece in _split_paragraph(text, max_tokens):
                    emit(el, piece, el.page, el.page)
                continue
            joined = "\n\n".join([*(e.text.strip() for e in buffer), text])
            if buffer and count_tokens(joined) > max_tokens:
                flush()
            buffer.append(Element("text", text, el.page, el.section_path))
        elif el.kind == "table":
            flush()
            for piece in _split_table(el.text.strip(), max_tokens):
                emit(el, piece, el.page, el.page)
        else:
            flush()
            emit(el, _figure_content(el), el.page, el.page)
    flush()
    return chunks
