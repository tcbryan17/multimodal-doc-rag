"""Comparison indexes at other chunk sizes (ADR 0011's chunk-size comparison, built in 0017).

Chunk size is fixed when a document is ingested, so comparing 256 / 500 / 1024 tokens needs
one index per size. Each lives in its own database (`rag_chunk256`, ...), never in `rag`.

Rebuilding costs embeddings only. The expensive part of the real ingest was one vision call
per figure, and a figure is always exactly one chunk whatever the chunk size (see
`chunking.chunk_document`), so its stored description is still right. We read every figure's
stored text from the source index and apply it to the re-chunked document **by position**: the
n-th figure of a document is the same figure in both, because the same parser read the same
bytes. Two checks back that assumption up, and a mismatch is an error rather than a guess:
- the source file's hash must equal the hash stored at ingest;
- each stored text must end with the caption the fresh parse produced for that position
  (stored content is either the caption alone, or `description + blank line + caption`).
"""

import dataclasses
import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from multimodal_doc_rag.chunking import chunk_document
from multimodal_doc_rag.corpus_ingest import parser_for
from multimodal_doc_rag.db.repository import document_exists, index_document
from multimodal_doc_rag.evals.index import drop_statement, with_db
from multimodal_doc_rag.fetch import ManifestEntry
from multimodal_doc_rag.protocols import Embedder, Parser
from multimodal_doc_rag.types import Chunk

Conn = psycopg.Connection[Any]


class ChunkIndexError(RuntimeError):
    """The comparison index can't be built as asked. The message says what to do."""


def chunk_db_name(max_tokens: int) -> str:
    if max_tokens < 1:
        raise ValueError(f"max_tokens must be >= 1, got {max_tokens}")
    return f"rag_chunk{max_tokens}"


@dataclass(frozen=True)
class StoredFigure:
    content: str  # the figure chunk's text as indexed: description + caption, or caption only
    informational: bool | None  # None = the vision call failed at ingest (ADR 0008)


@dataclass(frozen=True)
class StoredDocument:
    sha256: str  # of the source file when it was ingested
    figures: tuple[StoredFigure, ...]  # in document order


def load_stored_figures(conn: Conn) -> dict[str, StoredDocument]:
    """Every document's figure texts from the source index, keyed by doc_key."""
    docs = {
        str(key): (str(sha), list[StoredFigure]())
        for key, sha in conn.execute("SELECT doc_key, sha256 FROM documents").fetchall()
    }
    rows = conn.execute(
        "SELECT d.doc_key, c.content, c.informational FROM chunks c"
        " JOIN documents d ON d.id = c.document_id"
        " WHERE c.kind = 'figure' ORDER BY d.doc_key, c.ordinal"
    ).fetchall()
    for key, content, informational in rows:
        docs[str(key)][1].append(StoredFigure(str(content), informational))
    return {key: StoredDocument(sha, tuple(figures)) for key, (sha, figures) in docs.items()}


def with_stored_descriptions(
    chunks: Sequence[Chunk], stored: StoredDocument, doc_key: str
) -> list[Chunk]:
    """The chunks, with each figure chunk given its stored text and `informational` flag."""
    figure_positions = [i for i, c in enumerate(chunks) if c.kind == "figure"]
    if len(figure_positions) != len(stored.figures):
        raise ChunkIndexError(
            f"{doc_key}: parsing found {len(figure_positions)} figure(s) but the source index "
            f"stores {len(stored.figures)}. The parser has changed since the ingest: re-ingest "
            "the source index first (scripts/ingest_corpus.py --replace)."
        )
    out = list(chunks)
    for i, figure in zip(figure_positions, stored.figures, strict=True):
        caption = chunks[i].content
        if not figure.content.endswith(caption):
            raise ChunkIndexError(
                f"{doc_key}: stored figure text at chunk {chunks[i].ordinal} does not end with "
                f"the caption parsed now ({caption[:60]!r}). The figures no longer line up: "
                "re-ingest the source index first."
            )
        out[i] = dataclasses.replace(
            chunks[i], content=figure.content, informational=figure.informational
        )
    return out


def create_chunk_database(admin_url: str, target: str, recreate: bool) -> bool:
    """Make sure the empty database `target` exists; True if it was (re)created.

    An existing one is kept unless `recreate`, so an interrupted build resumes (finished
    documents are skipped). Connects to the `postgres` maintenance database, because CREATE
    and DROP DATABASE can't run inside a transaction or from the database being dropped.
    """
    with psycopg.connect(with_db(admin_url, "postgres"), autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target,)).fetchone()
        if exists is not None and not recreate:
            return False
        if exists is not None:
            admin.execute(drop_statement(target))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
        return True


@dataclass(frozen=True)
class ChunkIndexResult:
    doc_key: str
    status: str  # indexed | skipped-existing
    chunks: int = 0


def build_chunk_index(
    conn: Conn,
    entries: Sequence[ManifestEntry],
    data_dir: Path,
    stored: Mapping[str, StoredDocument],
    *,
    max_tokens: int,
    embedder: Embedder,
    parsers: Mapping[str, Parser] | None = None,
    log: Callable[[str], None] = print,
) -> list[ChunkIndexResult]:
    """Index every entry into `conn`'s database at `max_tokens`, one transaction per document.

    Makes embedding calls only. A BudgetExceededError (or any error) propagates after that
    document's transaction rolled back, leaving whole documents behind; re-run to continue.
    """
    results: list[ChunkIndexResult] = []
    for n, entry in enumerate(entries, 1):
        path = data_dir / entry.path
        source = stored.get(entry.doc_key)
        if source is None:
            raise ChunkIndexError(
                f"{entry.doc_key} is not in the source index: ingest it first "
                "(scripts/ingest_corpus.py)."
            )
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if source.sha256 != sha:
            raise ChunkIndexError(
                f"{entry.doc_key}: the file has changed since it was ingested, so the stored "
                "figure descriptions may not match. Re-ingest it first (--replace)."
            )
        if document_exists(conn, sha):  # before parsing: the PDF parse takes minutes
            log(f"[{n}/{len(entries)}] {entry.doc_key}: already there")
            results.append(ChunkIndexResult(entry.doc_key, "skipped-existing"))
            continue
        log(f"[{n}/{len(entries)}] {entry.doc_key} ...")
        parsed = parser_for(path, parsers).parse(path, entry.to_source_info())
        chunks = with_stored_descriptions(
            chunk_document(parsed, max_tokens=max_tokens), source, entry.doc_key
        )
        with conn.transaction():
            index_document(conn, parsed, chunks, embedder)
        results.append(ChunkIndexResult(entry.doc_key, "indexed", len(chunks)))
    return results
