"""The whole eval path over a real Postgres with fake models: ingest -> gold -> run -> report."""

from pathlib import Path
from typing import Any

import psycopg
import pytest

from multimodal_doc_rag.evals.gold import GoldItem, GoldPage, InjectionItem, load_gold, save_gold
from multimodal_doc_rag.evals.judge import FakeJudge
from multimodal_doc_rag.evals.report import render_json, render_markdown
from multimodal_doc_rag.evals.results import EvalReport, RunConfig
from multimodal_doc_rag.evals.runner import index_stats, run_eval, select_items
from multimodal_doc_rag.evals.wiring import PassThroughReranker
from multimodal_doc_rag.fakes import (
    CaptionFigureDescriber,
    EchoGenerator,
    HashingEmbedder,
    OverlapReranker,
    PlainTextParser,
)
from multimodal_doc_rag.ingest import ingest_document
from multimodal_doc_rag.models.cost import CostMeter
from multimodal_doc_rag.pipeline import RagPipeline
from multimodal_doc_rag.types import Corpus, SourceInfo

pytestmark = pytest.mark.db
EMB = HashingEmbedder()

ALTIMETER = "The altimeter measures altitude by sensing static pressure from the atmosphere."
VSI = "The vertical speed indicator shows the rate of climb or descent in feet per minute."


def _gold(id: str, **kw: Any) -> GoldItem:
    base: dict[str, Any] = {
        "id": id,
        "corpus": "faa",
        "split": "dev",
        "type": "fact",
        "answerable": True,
        "status": "verified",
    }
    return GoldItem.model_validate(base | kw)


def test_run_end_to_end(db_conn: psycopg.Connection[Any], tmp_path: Path) -> None:
    doc = tmp_path / "doc.txt"
    doc.write_text(f"# Instruments\n\n{ALTIMETER}\f{VSI}")
    ingest_document(
        db_conn,
        PlainTextParser(),
        doc,
        SourceInfo("doc-a", Corpus.FAA, "Doc A", "file://x"),
        embedder=EMB,
        describer=CaptionFigureDescriber(),
    )

    gold_path = tmp_path / "faa.jsonl"
    save_gold(
        gold_path,
        [
            _gold(
                "faa-dev-001",
                question="What does the altimeter measure?",
                reference_answer="altitude by sensing static pressure",
                gold_pages=[GoldPage(doc="doc-a", page_idx=0, page_label="1")],
            ),
            _gold(
                "faa-dev-002",
                question="What does the vertical speed indicator show?",
                reference_answer="rate of climb",
                gold_pages=[GoldPage(doc="doc-a", page_idx=5)],  # no such page: a retrieval miss
            ),
            _gold("faa-dev-003", question="Who won the 1998 World Cup?", answerable=False),
        ],
    )
    items = select_items(load_gold(gold_path), corpus="faa", split="dev")
    assert len(items) == 3

    pipeline = RagPipeline(
        db_conn, embedder=EMB, reranker=OverlapReranker(), generator=EchoGenerator()
    )
    cfg = RunConfig(
        label="e2e",
        started_utc="2026-11-07T00:00:00Z",
        git_commit="x",
        git_dirty=False,
        corpus="faa",
        split="dev",
        generator_model="fake/gen",
        judge_model="fake/judge",
        embedding_model=EMB.model_key,
        rerank_model=None,
        top_k=5,
        recall_k=5,
        candidates=30,
        budget_usd=1.0,
        include_drafts=False,
        limit=None,
        index=index_stats(db_conn, EMB.model_key),
        database="rag_test",
    )
    inj = [
        InjectionItem(
            id="i-1", kind="direct", question="altimeter", attack_goal="g", canary="ZEBRA"
        )
    ]
    report = run_eval(cfg, items, inj, pipeline, FakeJudge(), CostMeter(cap_usd=1.0))

    by_id = {r.id: r for r in report.items}
    assert by_id["faa-dev-001"].metrics["recall"] == 1.0
    verdict = by_id["faa-dev-001"].verdict
    assert verdict is not None and verdict.correctness == 1
    assert by_id["faa-dev-002"].metrics["recall"] == 0.0
    assert by_id["faa-dev-003"].metrics["abstention"] == 0.0  # EchoGenerator never says IDK
    assert all(r.retrieved for r in report.items) and not report.truncated
    assert report.injection[0].metrics["canary_in_answer"] == 0.0
    assert cfg.index["documents"] == 1 and int(cfg.index["chunks"]) >= 1

    md = render_markdown(report)
    assert "Retrieval misses (no gold page in the top-k): 1" in md and "faa-dev-002" in md
    assert EvalReport.model_validate_json(render_json(report)) == report


def test_no_rerank_pass_through_keeps_hybrid_order() -> None:
    ranked = PassThroughReranker().rerank("q", ["a", "b", "c"], 2)
    assert [i for i, _ in ranked] == [0, 1]
    assert ranked[0][1] > ranked[1][1]
