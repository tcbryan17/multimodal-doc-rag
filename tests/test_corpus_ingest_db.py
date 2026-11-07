"""corpus_ingest against Postgres: per-document transactions, replace, stale, retry.

All run inside `db_conn`'s rolled-back transaction, so each `conn.transaction()` in the code
under test is a SAVEPOINT here (and a real commit in production). One test asserts that.
"""

import hashlib
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.pq import TransactionStatus

from multimodal_doc_rag.corpus_ingest import retry_failures, run_ingest
from multimodal_doc_rag.db import repository as repo
from multimodal_doc_rag.fakes import HashingEmbedder
from multimodal_doc_rag.fetch import ManifestEntry
from multimodal_doc_rag.models.cost import BudgetExceededError, CostMeter
from multimodal_doc_rag.types import (
    Corpus,
    Element,
    Figure,
    FigureDescription,
    PageRef,
    ParsedDocument,
    SourceInfo,
)

pytestmark = pytest.mark.db

Conn = psycopg.Connection[Any]


class FigParser:
    """Each non-empty line of the file is a paragraph; a line 'FIG <n>' is a figure."""

    def parse(self, path: Path, source: SourceInfo) -> ParsedDocument:
        raw = path.read_bytes()
        els: list[Element] = []
        for line in raw.decode().splitlines():
            page = PageRef(0, "1")
            if line.startswith("FIG "):
                n = line[4:]
                cap = f"Figure {n}. A chart"
                f = Figure(n, cap, b"png-" + n.encode(), 2, 2)
                els.append(Element("figure", cap, page, ("Ch",), f))
            elif line.strip():
                els.append(Element("text", line, page, ("Ch",)))
        return ParsedDocument(source, hashlib.sha256(raw).hexdigest(), 1, tuple(els))


PARSERS: Any = {".txt": FigParser()}


class Describer:
    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode  # ok | boom | budget | decorative
        self.calls = 0

    def describe(self, png: bytes, caption: str, context: str) -> FigureDescription:
        self.calls += 1
        if self.mode == "boom":
            raise RuntimeError("vision down")
        if self.mode == "budget":
            raise BudgetExceededError("cap reached")
        return FigureDescription(self.mode == "ok", "A bar chart" if self.mode == "ok" else "")


def make_entry(data_dir: Path, key: str, text: str, split: str = "dev") -> ManifestEntry:
    (data_dir / f"{key}.txt").write_text(text)
    return ManifestEntry(
        key, Corpus.FAA, key.upper(), "https://x", None, None, f"{key}.txt", "s", split
    )


def ingest(
    conn: Conn, tmp: Path, entries: list[ManifestEntry], describer: Describer, **kw: Any
) -> Any:
    return run_ingest(
        conn, entries, tmp, embedder=HashingEmbedder(), describer=describer,
        meter=CostMeter(1.0), parsers=PARSERS, log=lambda _: None, **kw,
    )  # fmt: skip


def count(conn: Conn, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    assert row is not None
    return int(row[0])


def test_the_fixture_connection_is_inside_a_transaction(db_conn: Conn) -> None:
    # If this were IDLE, `conn.transaction()` in the code under test would really COMMIT to
    # rag_test and tests would leak into each other.
    assert db_conn.info.transaction_status == TransactionStatus.INTRANS


def test_ingests_documents_and_reports_counts(db_conn: Conn, tmp_path: Path) -> None:
    entries = [
        make_entry(tmp_path, "doc-a", "hello world\nFIG 1-1\nFIG 1-2"),
        make_entry(tmp_path, "doc-b", "other text", "heldout"),
    ]
    report = ingest(db_conn, tmp_path, entries, Describer())
    a, b = report.results
    assert (a.status, a.figures_total, a.figures_described, a.figures_degraded) == (
        "ingested",
        2,
        2,
        0,
    )
    assert (b.doc_key, b.split, b.status) == ("doc-b", "heldout", "ingested")
    assert count(db_conn, "SELECT count(*) FROM documents") == 2
    assert not report.budget_exceeded
    assert "ingested" in report.markdown()


def test_rerun_skips_existing_without_spending(db_conn: Conn, tmp_path: Path) -> None:
    entries = [make_entry(tmp_path, "doc-a", "hello\nFIG 1-1")]
    ingest(db_conn, tmp_path, entries, Describer())
    describer = Describer()
    report = ingest(db_conn, tmp_path, entries, describer)
    assert report.results[0].status == "skipped-existing"
    assert describer.calls == 0


def test_changed_source_without_replace_is_stale_and_spends_nothing(
    db_conn: Conn, tmp_path: Path
) -> None:
    ingest(db_conn, tmp_path, [make_entry(tmp_path, "doc-a", "hello\nFIG 1-1")], Describer())
    changed = make_entry(tmp_path, "doc-a", "hello again\nFIG 1-1")
    describer = Describer()
    report = ingest(db_conn, tmp_path, [changed], describer)
    assert report.results[0].status == "stale" and "--replace" in report.results[0].error
    assert describer.calls == 0  # we did not pay for figures and then hit the UNIQUE doc_key


def test_replace_swaps_the_document_atomically(db_conn: Conn, tmp_path: Path) -> None:
    ingest(
        db_conn, tmp_path, [make_entry(tmp_path, "doc-a", "old text\nFIG 1-1")], Describer("boom")
    )
    assert count(db_conn, "SELECT count(*) FROM ingest_failures WHERE document_id IS NOT NULL") == 1
    same = make_entry(tmp_path, "doc-a", "old text\nFIG 1-1")  # identical bytes: replace anyway
    report = ingest(db_conn, tmp_path, [same], Describer(), replace=True)
    assert report.results[0].status == "replaced"
    assert count(db_conn, "SELECT count(*) FROM documents") == 1
    assert count(db_conn, "SELECT count(*) FROM chunks WHERE content LIKE 'A bar chart%'") == 1
    # the old failure row survives with its document gone (SET NULL); the new doc has none
    assert count(db_conn, "SELECT count(*) FROM ingest_failures WHERE document_id IS NULL") == 1


def test_replace_failure_rolls_back_the_delete(db_conn: Conn, tmp_path: Path) -> None:
    entry = make_entry(tmp_path, "doc-a", "text\nFIG 1-1")
    ingest(db_conn, tmp_path, [entry], Describer())
    report = ingest(db_conn, tmp_path, [entry], Describer("budget"), replace=True)
    assert report.budget_exceeded
    assert count(db_conn, "SELECT count(*) FROM documents WHERE doc_key = 'doc-a'") == 1
    assert count(db_conn, "SELECT count(*) FROM chunks WHERE content LIKE 'A bar chart%'") == 1


def test_degraded_figures_are_counted_and_listed(db_conn: Conn, tmp_path: Path) -> None:
    entries = [make_entry(tmp_path, "doc-a", "x\nFIG 1-1\nFIG 1-2")]
    report = ingest(db_conn, tmp_path, entries, Describer("boom"))
    r = report.results[0]
    assert (r.figures_described, r.figures_degraded) == (0, 2)
    assert len(r.failures) == 2 and r.failures[0].startswith("doc-a#chunk")
    assert "RuntimeError: vision down" in report.markdown()


def test_budget_exhaustion_rolls_back_current_document_and_marks_the_rest(
    db_conn: Conn, tmp_path: Path
) -> None:
    class OneThenBudget(Describer):
        def describe(self, png: bytes, caption: str, context: str) -> FigureDescription:
            if self.calls >= 1:
                self.mode = "budget"
            return super().describe(png, caption, context)

    entries = [
        make_entry(tmp_path, "doc-a", "a\nFIG 1-1"),
        make_entry(tmp_path, "doc-b", "b\nFIG 2-1"),
        make_entry(tmp_path, "doc-c", "c\nFIG 3-1"),
    ]
    report = ingest(db_conn, tmp_path, entries, OneThenBudget())
    assert [r.status for r in report.results] == ["ingested", "failed", "not-reached"]
    assert report.budget_exceeded and "STOPPED" in report.markdown()
    keys = [r[0] for r in db_conn.execute("SELECT doc_key FROM documents")]
    assert keys == ["doc-a"]  # doc-b rolled back whole


def test_one_bad_document_does_not_stop_the_run(db_conn: Conn, tmp_path: Path) -> None:
    good = make_entry(tmp_path, "doc-good", "fine")
    bad = ManifestEntry("doc-bad", Corpus.FAA, "B", "https://x", None, None, "bad.docx", "s", "dev")
    (tmp_path / "bad.docx").write_text("?")
    report = ingest(db_conn, tmp_path, [bad, good], Describer())
    assert [r.status for r in report.results] == ["failed", "ingested"]
    assert "no parser" in report.results[0].error and str(tmp_path) not in report.results[0].error


# --- retry ----------------------------------------------------------------------------------------


def chart_row(conn: Conn) -> tuple[int, str, bool | None]:
    row = conn.execute(
        "SELECT id, content, informational FROM chunks WHERE kind = 'figure' ORDER BY id LIMIT 1"
    ).fetchone()
    assert row is not None
    return int(row[0]), str(row[1]), row[2]


def embeddings_of(conn: Conn, chunk_id: int) -> list[tuple[str, list[float]]]:
    rows = conn.execute(
        "SELECT model, embedding FROM embeddings WHERE chunk_id = %s ORDER BY model", (chunk_id,)
    ).fetchall()
    return [(m, list(v.to_list())) for m, v in rows]


def retry(conn: Conn, describer: Describer) -> Any:
    return retry_failures(
        conn,
        embedder=HashingEmbedder(),
        describer=describer,
        meter=CostMeter(1.0),
        log=lambda _: None,
    )


def test_retry_fixes_a_degraded_figure_end_to_end(db_conn: Conn, tmp_path: Path) -> None:
    ingest(db_conn, tmp_path, [make_entry(tmp_path, "doc-a", "intro\nFIG 1-1")], Describer("boom"))
    chunk_id, caption_only, informational = chart_row(db_conn)
    assert informational is None
    old = embeddings_of(db_conn, chunk_id)
    # a stale vector from a different model must go too: the text it described is gone
    db_conn.execute(
        "INSERT INTO embeddings (chunk_id, model, embedding) VALUES (%s, 'other@3', '[1,0,0]')",
        (chunk_id,),
    )

    describer = Describer("ok")
    report = retry(db_conn, describer)

    assert [r.status for r in report.results] == ["resolved"]
    _, content, informational = chart_row(db_conn)
    assert content == f"A bar chart\n\n{caption_only}" and informational is True
    new = embeddings_of(db_conn, chunk_id)
    assert [m for m, _ in new] == ["fake/hashing@64"]  # the 'other@3' row is gone
    assert new[0][1] != old[0][1]  # re-embedded from the new text
    expected = HashingEmbedder().embed_documents([f"DOC-A › Ch\n\n{content}"])[0]
    assert new[0][1] == pytest.approx(expected)
    assert count(db_conn, "SELECT count(*) FROM ingest_failures WHERE resolved_at IS NOT NULL") == 1
    # the full-text index follows the content (tsv is a generated column)
    assert count(db_conn, "SELECT count(*) FROM chunks WHERE tsv @@ to_tsquery('bar & chart')") == 1
    # idempotent: nothing left to retry, and no more spending
    assert retry(db_conn, describer).results == [] and describer.calls == 1


def test_retry_decorative_result_keeps_content_but_marks_it(db_conn: Conn, tmp_path: Path) -> None:
    ingest(db_conn, tmp_path, [make_entry(tmp_path, "doc-a", "FIG 1-1")], Describer("boom"))
    _, caption_only, _ = chart_row(db_conn)
    assert [r.status for r in retry(db_conn, Describer("decorative")).results] == ["resolved"]
    _, content, informational = chart_row(db_conn)
    assert content == caption_only and informational is False


def test_still_failing_retry_leaves_everything_unresolved(db_conn: Conn, tmp_path: Path) -> None:
    ingest(db_conn, tmp_path, [make_entry(tmp_path, "doc-a", "FIG 1-1")], Describer("boom"))
    chunk_id, before, _ = chart_row(db_conn)
    old = embeddings_of(db_conn, chunk_id)
    report = retry(db_conn, Describer("boom"))
    assert [r.status for r in report.results] == ["still-failing"]
    assert chart_row(db_conn) == (chunk_id, before, None)
    assert embeddings_of(db_conn, chunk_id) == old
    assert count(db_conn, "SELECT count(*) FROM ingest_failures WHERE resolved_at IS NULL") == 1


def test_retry_failure_after_embedding_rolls_back_the_figure(db_conn: Conn, tmp_path: Path) -> None:
    class BrokenEmbedder(HashingEmbedder):
        def embed_documents(self, texts: Any) -> list[list[float]]:
            raise RuntimeError("embedder down")

    ingest(db_conn, tmp_path, [make_entry(tmp_path, "doc-a", "FIG 1-1")], Describer("boom"))
    chunk_id, before, _ = chart_row(db_conn)
    old = embeddings_of(db_conn, chunk_id)
    report = retry_failures(
        db_conn, embedder=BrokenEmbedder(), describer=Describer("ok"),
        meter=CostMeter(1.0), log=lambda _: None,
    )  # fmt: skip
    assert report.results[0].status == "still-failing"
    assert chart_row(db_conn) == (chunk_id, before, None)  # the content UPDATE was undone
    assert embeddings_of(db_conn, chunk_id) == old


def test_retry_budget_exhaustion_stops(db_conn: Conn, tmp_path: Path) -> None:
    ingest(
        db_conn, tmp_path, [make_entry(tmp_path, "doc-a", "FIG 1-1\nFIG 1-2")], Describer("boom")
    )
    report = retry(db_conn, Describer("budget"))
    assert report.budget_exceeded and len(report.results) == 1
    assert count(db_conn, "SELECT count(*) FROM ingest_failures WHERE resolved_at IS NULL") == 2


def test_retry_reports_orphans_after_replace(db_conn: Conn, tmp_path: Path) -> None:
    entry = make_entry(tmp_path, "doc-a", "FIG 1-1")
    ingest(db_conn, tmp_path, [entry], Describer("boom"))
    ingest(db_conn, tmp_path, [entry], Describer("ok"), replace=True)
    describer = Describer("ok")
    report = retry(db_conn, describer)
    assert [r.status for r in report.results] == ["orphaned"]
    assert describer.calls == 0


# --- repository -----------------------------------------------------------------------------------


def test_delete_document_cascades_and_never_commits(db_conn: Conn, tmp_path: Path) -> None:
    ingest(db_conn, tmp_path, [make_entry(tmp_path, "doc-a", "x\nFIG 1-1")], Describer("boom"))
    assert repo.get_document_sha(db_conn, "doc-a") is not None
    assert repo.delete_document(db_conn, "doc-a") is True
    assert repo.delete_document(db_conn, "doc-a") is False
    assert repo.get_document_sha(db_conn, "doc-a") is None
    for table in ("chunks", "embeddings", "figures"):
        assert count(db_conn, f"SELECT count(*) FROM {table}") == 0, table
    assert count(db_conn, "SELECT count(*) FROM ingest_failures WHERE document_id IS NULL") == 1


def test_ingest_failures_has_resolved_at(db_conn: Conn) -> None:
    cols = {
        r[0]
        for r in db_conn.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'ingest_failures'"
        )
    }
    assert "resolved_at" in cols
