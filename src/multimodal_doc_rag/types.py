"""Core data types that flow through the pipeline: parse → chunk → index → retrieve → answer.

Frozen dataclasses: values, not objects with behaviour. Each stage takes one of these and
returns the next, which keeps the stages independently testable (ADR 0012).

Pages are always a `PageRef` with two parts (ADR 0005 / 0010):
- `idx`: 0-based position within the source file. Use it for ordering and range checks.
- `label`: the printed page number, e.g. "8-22" or "37". Show it to users. It can't be
  compared as a number ("4-9" sorts after "4-12" as text), and some pages don't print one.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

ElementKind = Literal["text", "table", "figure"]


class Corpus(StrEnum):
    TEN_K = "10k"
    FAA = "faa"


@dataclass(frozen=True)
class PageRef:
    idx: int
    label: str | None

    def __post_init__(self) -> None:
        if self.idx < 0:
            raise ValueError(f"page idx must be >= 0, got {self.idx}")


@dataclass(frozen=True)
class SourceInfo:
    """What we know about a document before parsing it (from the fetch manifest)."""

    doc_key: str  # short slug, used in citations and filters, e.g. "aapl-10k-2026"
    corpus: Corpus
    title: str  # display title, e.g. "FAA-H-8083-25C, Ch. 8: Flight Instruments"
    source_url: str
    company: str | None = None  # 10-Ks only
    fiscal_year: int | None = None  # 10-Ks only


@dataclass(frozen=True)
class Figure:
    """A rendered figure region (ADR 0006/0008). Most handbook figures are vector, so `png`
    is a render of a page region, not an extracted embedded image."""

    number: str | None  # printed figure number, e.g. "8-22"; None when uncaptioned
    caption: str
    png: bytes
    width: int
    height: int
    bbox: tuple[float, float, float, float] | None = None  # PDF points (x0, y0, x1, y1)
    is_vector: bool | None = None


@dataclass(frozen=True)
class Element:
    """One parsed unit of a document: a paragraph, a table (as Markdown) or a figure.

    For a figure, `text` is its caption text, so it's still findable by keyword search.
    """

    kind: ElementKind
    text: str
    page: PageRef
    section_path: tuple[str, ...]  # e.g. ("Item 7", "Liquidity and Capital Resources")
    figure: Figure | None = None

    def __post_init__(self) -> None:
        if (self.kind == "figure") != (self.figure is not None):
            raise ValueError("an Element has a Figure if and only if kind == 'figure'")
        if self.kind != "figure" and not self.text.strip():
            raise ValueError(f"{self.kind} element must have text")


@dataclass(frozen=True)
class ParsedDocument:
    source: SourceInfo
    sha256: str  # of the source file bytes; re-ingesting the same hash is a no-op
    page_count: int
    elements: tuple[Element, ...]  # in reading order


@dataclass(frozen=True)
class Chunk:
    """The unit of retrieval AND of citation (ADR 0007). May span a page break."""

    ordinal: int  # position within the document
    kind: ElementKind
    section_path: tuple[str, ...]
    page_start: PageRef
    page_end: PageRef
    content: str  # what the LLM reads (a figure's description + caption, once described)
    context_header: str  # e.g. "Apple 10-K FY2026 › Item 7 › Liquidity"
    figure: Figure | None = None
    informational: bool | None = None  # figures only, set by the FigureDescriber

    def __post_init__(self) -> None:
        if self.page_end.idx < self.page_start.idx:
            raise ValueError("page_end must not come before page_start")
        if (self.kind == "figure") != (self.figure is not None):
            raise ValueError("a Chunk has a Figure if and only if kind == 'figure'")

    @property
    def embed_text(self) -> str:
        """What gets embedded: the context header first, so the chunk carries where it's from."""
        return f"{self.context_header}\n\n{self.content}"


@dataclass(frozen=True)
class Passage:
    """A retrieved chunk, as handed to the reranker and the generator."""

    chunk_id: int
    doc_key: str
    doc_title: str
    kind: ElementKind
    page_start: PageRef
    page_end: PageRef
    content: str
    context_header: str
    score: float  # meaning depends on the stage: RRF score, then reranker relevance


@dataclass(frozen=True)
class FigureDescription:
    informational: bool  # False for decorative photos: they keep only their caption (ADR 0008)
    description: str


@dataclass(frozen=True)
class GeneratedAnswer:
    text: str
    cited_chunk_ids: tuple[int, ...]  # must be a subset of the passages provided
