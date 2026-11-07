"""Trivial, deterministic stand-ins for the protocols in `protocols.py` (ADR 0012).

They make the walking skeleton run end to end with no network, no API key and no cost.
Keep them simple: they need to *behave plausibly* (similar texts get similar vectors, word
overlap counts as relevance), not to be good.
"""

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from multimodal_doc_rag.types import (
    Element,
    FigureDescription,
    GeneratedAnswer,
    PageRef,
    ParsedDocument,
    Passage,
    SourceInfo,
)

IDK = "I don't know based on the available documents."

_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class HashingEmbedder:
    """Bag-of-words "embedding": each word adds 1 to a bucket chosen by hashing it.

    Texts sharing words end up with similar vectors, which is all the tests need. Uses
    hashlib, not hash(), because Python randomises hash() per process.
    """

    def __init__(self, dim: int = 64) -> None:
        self._dim = dim

    @property
    def model_key(self) -> str:
        return f"fake/hashing@{self._dim}"

    @property
    def dim(self) -> int:
        return self._dim

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for word in _words(text):
            bucket = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=4).digest())
            vec[bucket % self._dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            vec[0] = 1.0  # empty text still gets a valid unit vector
            return vec
        return [v / norm for v in vec]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class OverlapReranker:
    """Relevance = share of the query's words that appear in the document."""

    def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[tuple[int, float]]:
        q = set(_words(query))
        scored = [
            (i, len(q & set(_words(doc))) / len(q) if q else 0.0) for i, doc in enumerate(documents)
        ]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))  # stable: ties keep input order
        return scored[:top_n]


class EchoGenerator:
    """Quotes the first passage and cites it; with no passages, says it doesn't know."""

    def generate(
        self, question: str, passages: Sequence[Passage], figures: Mapping[int, bytes]
    ) -> GeneratedAnswer:
        if not passages:
            return GeneratedAnswer(text=IDK, cited_chunk_ids=())
        first = passages[0]
        return GeneratedAnswer(
            text=f"{first.content.strip()[:200]} [{first.chunk_id}]",
            cited_chunk_ids=(first.chunk_id,),
        )


class CaptionFigureDescriber:
    """Calls a figure informational if it has a caption, and 'describes' it by its caption."""

    def describe(self, png: bytes, caption: str, context: str) -> FigureDescription:
        informational = bool(caption.strip())
        description = f"Figure showing: {caption.strip()}" if informational else ""
        return FigureDescription(informational=informational, description=description)


class PlainTextParser:
    """Parses a tiny plain-text format, for tests that need a document without HTML or PDF.

    - A form feed (\\f) starts a new page. Pages are labelled "1", "2", ...
    - A line starting with "# " is a level-1 heading, "## " a level-2 heading.
    - Blank lines separate paragraphs.
    """

    def parse(self, path: Path, source: SourceInfo) -> ParsedDocument:
        raw = path.read_bytes()
        pages = raw.decode("utf-8").split("\f")
        elements: list[Element] = []
        headings: list[str] = []
        for idx, page_text in enumerate(pages):
            page = PageRef(idx=idx, label=str(idx + 1))
            for block in re.split(r"\n\s*\n", page_text):
                block = block.strip()
                if not block:
                    continue
                if block.startswith("## "):
                    headings = headings[:1] + [block[3:].strip()]
                elif block.startswith("# "):
                    headings = [block[2:].strip()]
                else:
                    elements.append(
                        Element(kind="text", text=block, page=page, section_path=tuple(headings))
                    )
        return ParsedDocument(
            source=source,
            sha256=hashlib.sha256(raw).hexdigest(),
            page_count=len(pages),
            elements=tuple(elements),
        )
