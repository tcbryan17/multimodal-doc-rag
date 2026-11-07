"""The pipeline's seams (ADR 0012). Each is a `typing.Protocol`: anything with these methods
fits, with no inheritance needed. Every protocol has a trivial fake in `fakes.py`, and one
contract-test suite in `tests/contracts/` that runs against every implementation, fake and
real. Replacing a fake with the real thing means adding it to that suite and passing.

Deliberately absent: chunk-size knobs, DB handles, model-specific options. Those belong to
the implementations' constructors, not to the interface.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from multimodal_doc_rag.types import (
    FigureDescription,
    GeneratedAnswer,
    ParsedDocument,
    Passage,
    SourceInfo,
)


class Parser(Protocol):
    """Source file → elements in reading order, each with page, section path and kind."""

    def parse(self, path: Path, source: SourceInfo) -> ParsedDocument: ...


class Embedder(Protocol):
    """Text → unit-length vectors of a fixed dimension.

    Documents and queries are separate methods because some models (Qwen3 among them) embed
    queries with an instruction prefix and documents without one.
    """

    @property
    def model_key(self) -> str:
        """The `embeddings.model` value, '<model id>@<dims>' (see Settings.embedding_key)."""
        ...

    @property
    def dim(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class Reranker(Protocol):
    """Scores each document's relevance to the query and keeps the best `top_n`.

    Returns (index into `documents`, score) pairs, best first.
    """

    def rerank(
        self, query: str, documents: Sequence[str], top_n: int
    ) -> list[tuple[int, float]]: ...


class Generator(Protocol):
    """Answers from the given passages only, citing them by chunk id, or says it doesn't know.

    `figures` maps chunk_id → PNG for figure passages, so a vision model can read the actual
    chart (ADR 0008).
    """

    def generate(
        self, question: str, passages: Sequence[Passage], figures: Mapping[int, bytes]
    ) -> GeneratedAnswer: ...


class FigureDescriber(Protocol):
    """One vision call per figure at index time: is it informational, and what does it show?"""

    def describe(self, png: bytes, caption: str, context: str) -> FigureDescription: ...
