"""The chunk-size comparison index (ADR 0011, 0017): re-chunk and re-embed, reusing the figure
descriptions already paid for. The embedder comparison's helpers are tested here too."""

import hashlib
from pathlib import Path
from typing import Any

import psycopg
import pytest

from multimodal_doc_rag.corpus_ingest import run_ingest
from multimodal_doc_rag.db import repository as repo
from multimodal_doc_rag.evals.chunk_index import (
    ChunkIndexError,
    StoredDocument,
    StoredFigure,
    build_chunk_index,
    chunk_db_name,
    load_stored_figures,
    with_stored_descriptions,
)
from multimodal_doc_rag.fakes import HashingEmbedder
from multimodal_doc_rag.fetch import ManifestEntry
from multimodal_doc_rag.models.cost import CostMeter
from multimodal_doc_rag.search import has_vector_index
from multimodal_doc_rag.types import (
    Chunk,
    Corpus,
    Element,
    Figure,
    FigureDescription,
    PageRef,
    ParsedDocument,
    SourceInfo,
)

Conn = psycopg.Connection[Any]
PAGE = PageRef(0, "1")
LONG = "The altimeter measures altitude. " * 30  # ~250 tokens: one chunk at 500, many at 20


class FigParser:
    """Each non-empty line is a paragraph; a line 'FIG <n>' is a figure."""

    def parse(self, path: Path, source: SourceInfo) -> ParsedDocument:
        raw = path.read_bytes()
        els: list[Element] = []
        for line in raw.decode().splitlines():
            if line.startswith("FIG "):
                n = line[4:]
                cap = f"Figure {n}. A chart"
                els.append(
                    Element(
                        "figure", cap, PAGE, ("Ch",), Figure(n, cap, b"png-" + n.encode(), 2, 2)
                    )
                )
            elif line.strip():
                els.append(Element("text", line, PAGE, ("Ch",)))
        return ParsedDocument(source, hashlib.sha256(raw).hexdigest(), 1, tuple(els))


PARSERS: Any = {".txt": FigParser()}


class Describer:
    """Figure 1-2 fails (so it is stored caption-only); the others get a description."""

    def describe(self, png: bytes, caption: str, context: str) -> FigureDescription:
        if b"1-2" in png:
            raise RuntimeError("vision down")
        return FigureDescription(True, f"A bar chart of {png.decode()}")


def make_entry(data_dir: Path, key: str, text: str) -> ManifestEntry:
    (data_dir / f"{key}.txt").write_text(text)
    return ManifestEntry(
        key, Corpus.FAA, key.upper(), "https://x", None, None, f"{key}.txt", "s", "dev"
    )


def figure_chunk(content: str) -> Chunk:
    fig = Figure("1", content, b"png", 2, 2)
    return Chunk(0, "figure", ("Ch",), PAGE, PAGE, content, "Doc › Ch", fig)


def text_chunk(content: str) -> Chunk:
    return Chunk(0, "text", ("Ch",), PAGE, PAGE, content, "Doc › Ch")


# --- pure --------------------------------------------------------------------------------------


def test_database_name_carries_the_chunk_size() -> None:
    assert chunk_db_name(256) == "rag_chunk256"
    with pytest.raises(ValueError):
        chunk_db_name(0)


def test_stored_descriptions_are_applied_to_figure_chunks_in_order() -> None:
    chunks = [text_chunk("para"), figure_chunk("Figure 1. A"), figure_chunk("Figure 2. B")]
    stored = StoredDocument(
        "sha",
        (
            StoredFigure("Bars rising.\n\nFigure 1. A", True),
            StoredFigure("Figure 2. B", None),  # degraded at ingest: caption only
        ),
    )
    out = with_stored_descriptions(chunks, stored, "doc")
    assert out[0] == chunks[0]  # text chunks are untouched
    assert (out[1].content, out[1].informational) == ("Bars rising.\n\nFigure 1. A", True)
    assert (out[2].content, out[2].informational) == ("Figure 2. B", None)
    assert out[1].figure is chunks[1].figure  # the freshly rendered PNG is kept


def test_a_mismatch_with_the_stored_figures_is_an_error_not_a_guess() -> None:
    chunks = [figure_chunk("Figure 1. A")]
    with pytest.raises(ChunkIndexError, match="1 figure.*stores 2"):
        with_stored_descriptions(
            chunks, StoredDocument("s", (StoredFigure("x", True), StoredFigure("y", True))), "doc"
        )
    # Same count, but the stored text belongs to a different figure (its caption differs).
    with pytest.raises(ChunkIndexError, match="does not end with"):
        with_stored_descriptions(
            chunks, StoredDocument("s", (StoredFigure("Desc.\n\nFigure 9. Z", True),)), "doc"
        )


# --- against Postgres --------------------------------------------------------------------------


@pytest.mark.db
def test_rebuilds_at_another_chunk_size_reusing_stored_descriptions(
    db_conn: Conn, tmp_path: Path
) -> None:
    entry = make_entry(tmp_path, "doc-a", f"{LONG}\nFIG 1-1\nFIG 1-2\nshort tail")
    emb = HashingEmbedder()
    run_ingest(
        db_conn, [entry], tmp_path, embedder=emb, describer=Describer(),
        meter=CostMeter(1.0), parsers=PARSERS, log=lambda _: None,
    )  # fmt: skip
    before = db_conn.execute("SELECT count(*) FROM chunks WHERE kind = 'text'").fetchone()
    assert before is not None

    stored = load_stored_figures(db_conn)
    sha = hashlib.sha256((tmp_path / "doc-a.txt").read_bytes()).hexdigest()
    assert stored == {
        "doc-a": StoredDocument(
            sha,
            (
                StoredFigure("A bar chart of png-1-1\n\nFigure 1-1. A chart", True),
                StoredFigure("Figure 1-2. A chart", None),
            ),
        )
    }

    # The comparison index is a separate database in real use. Here the one test database
    # plays both parts: read the stored figures, drop the document, rebuild it smaller.
    repo.delete_document(db_conn, "doc-a")
    results = build_chunk_index(
        db_conn, [entry], tmp_path, stored, max_tokens=20, embedder=emb,
        parsers=PARSERS, log=lambda _: None,
    )  # fmt: skip
    assert [(r.doc_key, r.status) for r in results] == [("doc-a", "indexed")]

    after = db_conn.execute("SELECT count(*) FROM chunks WHERE kind = 'text'").fetchone()
    assert after is not None and after[0] > before[0]  # smaller chunks, so more of them
    assert results[0].chunks == after[0] + 2
    figures = db_conn.execute(
        "SELECT content, informational FROM chunks WHERE kind = 'figure' ORDER BY ordinal"
    ).fetchall()
    # No describer was involved: the descriptions (and the degraded one) came from `stored`.
    assert figures == [
        ("A bar chart of png-1-1\n\nFigure 1-1. A chart", True),
        ("Figure 1-2. A chart", None),
    ]
    assert repo.count_missing_embeddings(db_conn, emb.model_key) == (0, 0)

    again = build_chunk_index(
        db_conn, [entry], tmp_path, stored, max_tokens=20, embedder=emb,
        parsers=PARSERS, log=lambda _: None,
    )  # fmt: skip
    assert [r.status for r in again] == ["skipped-existing"]  # a re-run resumes


@pytest.mark.db
def test_refuses_a_document_the_source_index_does_not_match(db_conn: Conn, tmp_path: Path) -> None:
    entry = make_entry(tmp_path, "doc-a", "text\nFIG 1-1")
    kw: Any = {"max_tokens": 20, "embedder": HashingEmbedder(), "parsers": PARSERS}
    with pytest.raises(ChunkIndexError, match="not in the source index"):
        build_chunk_index(db_conn, [entry], tmp_path, {}, log=lambda _: None, **kw)
    stale = {"doc-a": StoredDocument("another-sha", ())}
    with pytest.raises(ChunkIndexError, match="changed since"):
        build_chunk_index(db_conn, [entry], tmp_path, stale, log=lambda _: None, **kw)
    assert db_conn.execute("SELECT count(*) FROM documents").fetchone() == (0,)


@pytest.mark.db
def test_missing_embeddings_are_counted_per_model(db_conn: Conn, tmp_path: Path) -> None:
    entry = make_entry(tmp_path, "doc-a", "hello world\nsecond paragraph here")
    run_ingest(
        db_conn, [entry], tmp_path, embedder=HashingEmbedder(), describer=Describer(),
        meter=CostMeter(1.0), parsers=PARSERS, log=lambda _: None,
    )  # fmt: skip
    assert repo.count_missing_embeddings(db_conn, HashingEmbedder().model_key) == (0, 0)
    chunks, tokens = repo.count_missing_embeddings(db_conn, "another/model@8")
    assert chunks == 1 and tokens > 0  # the two short paragraphs share one chunk
    other = HashingEmbedder(dim=8)
    assert repo.embed_missing(db_conn, other) == 1
    assert repo.count_missing_embeddings(db_conn, other.model_key) == (0, 0)


@pytest.mark.db
def test_vector_index_lookup_knows_which_models_have_one(db_conn: Conn) -> None:
    # Created by migrations/0001_init.sql; a model without one still works, by sequential scan.
    assert has_vector_index(db_conn, "qwen/qwen3-embedding-8b@1024")
    assert has_vector_index(db_conn, "openai/text-embedding-3-small@1536")
    assert not has_vector_index(db_conn, "fake/hashing@64")
