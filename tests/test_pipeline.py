"""RagPipeline against a real Postgres, with fake models."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import psycopg
import pytest

from multimodal_doc_rag.contracts import AskRequest
from multimodal_doc_rag.fakes import (
    IDK,
    CaptionFigureDescriber,
    EchoGenerator,
    HashingEmbedder,
    OverlapReranker,
    PlainTextParser,
)
from multimodal_doc_rag.ingest import ingest_document
from multimodal_doc_rag.parsing.handbook_pdf import HandbookPdfParser
from multimodal_doc_rag.pipeline import RagPipeline
from multimodal_doc_rag.types import Corpus, GeneratedAnswer, Passage, SourceInfo

pytestmark = pytest.mark.db

Conn = psycopg.Connection[Any]
EMB = HashingEmbedder()
LONG = "word " * 100 + "tail"


class BoomReranker:
    def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[tuple[int, float]]:
        raise TimeoutError("reranker down")


class SpyGenerator:
    def __init__(self, cite: tuple[int, ...] = ()) -> None:
        self.calls = 0
        self.cite = cite
        self.passages: list[Passage] = []

    def generate(
        self, question: str, passages: Sequence[Passage], figures: Mapping[int, bytes]
    ) -> GeneratedAnswer:
        self.calls += 1
        self.passages = list(passages)
        return GeneratedAnswer("answer", self.cite or (passages[0].chunk_id,))


def _ingest(conn: Conn, tmp_path: Path, key: str, corpus: Corpus, text: str) -> None:
    path = tmp_path / f"{key}.txt"
    path.write_text(text)
    src = SourceInfo(key, corpus, f"Title {key}", "file://x")
    ingest_document(
        conn, PlainTextParser(), path, src, embedder=EMB, describer=CaptionFigureDescriber()
    )


def _pipeline(conn: Conn, generator: Any = None, reranker: Any = None, **kw: Any) -> RagPipeline:
    return RagPipeline(
        conn,
        embedder=EMB,
        reranker=reranker or OverlapReranker(),
        generator=generator or EchoGenerator(),
        **kw,
    )


def test_empty_db_returns_idk_without_calling_generator(db_conn: Conn) -> None:
    gen = SpyGenerator()
    resp = _pipeline(db_conn, gen).ask(AskRequest(question="anything at all"))
    assert resp.answer == IDK
    assert resp.citations == []
    assert gen.calls == 0
    assert [t.step for t in resp.trace] == ["retrieve", "rerank", "figures", "generate"]


def test_rerank_failure_falls_back_to_hybrid_order(db_conn: Conn, tmp_path: Path) -> None:
    _ingest(db_conn, tmp_path, "a", Corpus.FAA, "# Ch\n\naltimeter pressure\n\nairspeed indicator")
    gen = SpyGenerator()
    resp = _pipeline(db_conn, gen, reranker=BoomReranker(), top_k=1).ask(
        AskRequest(question="altimeter pressure")
    )
    assert resp.answer == "answer"
    assert len(gen.passages) == 1
    assert resp.trace[1].step == "rerank"
    assert resp.trace[1].detail == "rerank skipped: TimeoutError"


def test_reranker_scores_replace_rrf_scores_and_top_k_applies(
    db_conn: Conn, tmp_path: Path
) -> None:
    text = "# Ch\n\nalpha one\n\nalpha two\n\nalpha three"
    _ingest(db_conn, tmp_path, "a", Corpus.FAA, text)
    gen = SpyGenerator()
    _pipeline(db_conn, gen, top_k=2).ask(AskRequest(question="alpha"))
    assert len(gen.passages) <= 2
    assert all(p.score == 1.0 for p in gen.passages)  # OverlapReranker: full overlap


def test_filters_passed_through(db_conn: Conn, tmp_path: Path) -> None:
    # Texts must differ: ingestion de-duplicates on the file hash.
    _ingest(db_conn, tmp_path, "faa-doc", Corpus.FAA, "# Ch\n\nshared topic words")
    _ingest(db_conn, tmp_path, "tenk-doc", Corpus.TEN_K, "# Ch\n\nshared topic words again")
    gen = SpyGenerator()
    pipe = _pipeline(db_conn, gen)
    pipe.ask(AskRequest(question="shared topic", corpus="faa"))
    assert {p.doc_key for p in gen.passages} == {"faa-doc"}
    pipe.ask(AskRequest(question="shared topic", doc="tenk-doc"))
    assert {p.doc_key for p in gen.passages} == {"tenk-doc"}


def test_citation_fields_and_labels(db_conn: Conn, tmp_path: Path) -> None:
    # Two pages (labels "1" and "2"), each a long paragraph, so the snippet must be trimmed.
    _ingest(db_conn, tmp_path, "a", Corpus.FAA, f"# Ch\n\n{LONG}\f{LONG}")
    resp = _pipeline(db_conn).ask(AskRequest(question="word tail"))
    assert resp.citations
    c = resp.citations[0]
    assert c.doc == "Title a"
    assert c.page == "1"
    assert c.page_end is None or c.page_end == "2"
    assert c.image_url is None
    assert len(c.snippet) <= 201
    assert c.snippet.endswith("…")
    assert c.snippet.rstrip("…").endswith("word")  # trimmed at a word boundary


def test_trace_has_four_timed_steps(db_conn: Conn, tmp_path: Path) -> None:
    _ingest(db_conn, tmp_path, "a", Corpus.FAA, "# Ch\n\naltimeter")
    resp = _pipeline(db_conn).ask(AskRequest(question="altimeter"))
    assert [t.step for t in resp.trace] == ["retrieve", "rerank", "figures", "generate"]
    assert all(isinstance(t.ms, int) and t.ms >= 0 for t in resp.trace)
    assert resp.trace[0].detail == "1 candidates"


def test_unknown_cited_ids_are_ignored(db_conn: Conn, tmp_path: Path) -> None:
    _ingest(db_conn, tmp_path, "a", Corpus.FAA, "# Ch\n\naltimeter")
    resp = _pipeline(db_conn, SpyGenerator(cite=(999999,))).ask(AskRequest(question="altimeter"))
    assert resp.citations == []


class SpyFiguresGenerator(SpyGenerator):
    """Also records the `figures` argument, to prove the pipeline hands over the PNGs."""

    def __init__(self) -> None:
        super().__init__()
        self.figures: dict[int, bytes] = {}

    def generate(
        self, question: str, passages: Sequence[Passage], figures: Mapping[int, bytes]
    ) -> GeneratedAnswer:
        self.figures = dict(figures)
        return super().generate(question, passages, figures)


def test_figure_passages_get_image_url_and_generator_gets_their_pngs(
    db_conn: Conn, mini_handbook_pdf: Path
) -> None:
    src = SourceInfo("mini-phak", Corpus.FAA, "Mini Handbook", "file://mini.pdf")
    ingest_document(
        db_conn,
        HandbookPdfParser(),
        mini_handbook_pdf,
        src,
        embedder=EMB,
        describer=CaptionFigureDescriber(),
    )
    spy = SpyFiguresGenerator()
    question = "Lift versus angle of attack airspeed indicator"
    _pipeline(db_conn, spy, top_k=10).ask(AskRequest(question=question))

    figure_ids = {p.chunk_id for p in spy.passages if p.kind == "figure"}
    assert figure_ids
    assert any(p.kind != "figure" for p in spy.passages)
    # The generator receives PNG bytes for figure passages only.
    assert set(spy.figures) == figure_ids
    assert all(png.startswith(b"\x89PNG") for png in spy.figures.values())

    # Cite every passage: figure citations carry a relative image_url, text ones do not.
    spy.cite = tuple(p.chunk_id for p in spy.passages)
    resp = _pipeline(db_conn, spy, top_k=10).ask(AskRequest(question=question))
    assert len(resp.citations) == len(spy.passages)
    for passage, citation in zip(spy.passages, resp.citations, strict=True):
        expected = f"/figures/{passage.chunk_id}.png" if passage.kind == "figure" else None
        assert citation.image_url == expected
