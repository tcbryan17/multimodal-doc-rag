"""Ingestion glue: parse → chunk → describe figures → index (one document).

Never commits: the caller owns the transaction (see db/repository.py), so a whole document
lands atomically or not at all.
"""

import dataclasses
from pathlib import Path
from typing import Any

import psycopg

from multimodal_doc_rag.chunking import chunk_document
from multimodal_doc_rag.db.repository import document_exists, index_document, record_ingest_failure
from multimodal_doc_rag.models.cost import BudgetExceededError
from multimodal_doc_rag.protocols import Embedder, FigureDescriber, Parser
from multimodal_doc_rag.types import SourceInfo


def ingest_document(
    conn: psycopg.Connection[Any],
    parser: Parser,
    path: Path,
    source: SourceInfo,
    *,
    embedder: Embedder,
    describer: FigureDescriber,
    max_tokens: int = 500,
) -> int | None:
    """Ingest one file. Returns the new document id, or None if it was already ingested."""
    parsed = parser.parse(path, source)
    if document_exists(conn, parsed.sha256):
        return None  # check before describing: vision calls cost money

    chunks = chunk_document(parsed, max_tokens=max_tokens)
    failures: list[tuple[int, str]] = []  # (chunk ordinal, error)
    for i, chunk in enumerate(chunks):
        if chunk.figure is None:
            continue
        try:
            result = describer.describe(
                chunk.figure.png, chunk.figure.caption, chunk.context_header
            )
        except BudgetExceededError:
            raise  # out of money is not a figure failure: stop the whole run
        except Exception as exc:  # noqa: BLE001 - any failure degrades, never aborts (ADR 0008)
            # Keep the caption-only chunk so the figure is still findable by its caption.
            failures.append((chunk.ordinal, f"{type(exc).__name__}: {exc}"))
            continue
        if result.informational:
            content = f"{result.description}\n\n{chunk.content}"
            chunks[i] = dataclasses.replace(chunk, content=content, informational=True)
        else:
            chunks[i] = dataclasses.replace(chunk, informational=False)

    document_id = index_document(conn, parsed, chunks, embedder)
    # Recorded after indexing so the failure rows can point at the document.
    for ordinal, error in failures:
        record_ingest_failure(
            conn, document_id, "describe", f"{source.doc_key}#chunk{ordinal}", error
        )
    return document_id
