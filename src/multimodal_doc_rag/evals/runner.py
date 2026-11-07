"""The eval runner: ask every selected question, score it, grade it, and collect a report.

Design points worth being able to explain:
- **One CostMeter** is shared by the embedder, reranker, generator and judge (they all go
  through the same OpenRouterClient), so the cap covers the whole run. When it trips we stop,
  keep everything finished so far and say so in the report (`truncated`).
- **Latency excludes the judge** (the user never waits for it); **cost is split** into
  answering cost (what a real question costs) and judge cost (the price of measuring).
- A failure on one question (a provider error) is recorded and the run goes on. Only the
  spending cap stops the run.
"""

import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

import psycopg

from multimodal_doc_rag.contracts import AskRequest
from multimodal_doc_rag.evals.gold import GoldItem, InjectionItem
from multimodal_doc_rag.evals.judge import Judge, JudgeVerdict
from multimodal_doc_rag.evals.metrics import item_metrics
from multimodal_doc_rag.evals.results import (
    EvalReport,
    InjectionResult,
    ItemResult,
    RetrievedPassage,
    RunConfig,
)
from multimodal_doc_rag.models.cost import BudgetExceededError, CostMeter
from multimodal_doc_rag.pipeline import PipelineRun


class Runnable(Protocol):
    def run(self, request: AskRequest) -> PipelineRun: ...


def select_items(
    items: Sequence[GoldItem],
    *,
    corpus: str | None,
    split: str,
    include_drafts: bool = False,
    limit: int | None = None,
) -> list[GoldItem]:
    """Items for a run: the right corpus and split, and verified (rejected never; drafts only
    when asked, for smoke tests). Ordered by id so `--limit` is reproducible."""
    allowed = {"verified", "draft"} if include_drafts else {"verified"}
    chosen = [
        i
        for i in sorted(items, key=lambda i: i.id)
        if i.split == split and i.status in allowed and (corpus is None or i.corpus == corpus)
    ]
    return chosen if limit is None else chosen[:limit]


def _safe_judge(
    judge: Judge,
    item: GoldItem | InjectionItem,
    answer: str,
    run: PipelineRun,
    meter: CostMeter,
) -> tuple[JudgeVerdict | None, str | None, float]:
    """Grade, never raising except to nothing: returns (verdict, error, cost)."""
    before = meter.spent_usd
    try:
        verdict = judge.grade(item, answer, run.passages)
    except BudgetExceededError:
        return None, "judge skipped: spending cap reached", meter.spent_usd - before
    except Exception as exc:  # noqa: BLE001 - one bad judge reply must not lose the answer
        return None, f"{type(exc).__name__}: {exc}", meter.spent_usd - before
    return verdict, None, meter.spent_usd - before


def evaluate_item(
    item: GoldItem,
    pipeline: Runnable,
    judge: Judge | None,
    meter: CostMeter,
    recall_k: int = 5,
) -> ItemResult:
    """Answer one gold question and score it. Raises only BudgetExceededError."""
    result = ItemResult(
        id=item.id,
        corpus=item.corpus,
        split=item.split,
        type=item.type,
        question=item.question,
        answerable=item.answerable,
        reference_answer=item.reference_answer,
        gold_pages=item.gold_pages,
    )
    spent_before = meter.spent_usd
    started = time.perf_counter()
    try:
        # Filter by the item's corpus: the real product lets users search everything, but a
        # corpus filter keeps the two corpora from competing in each other's retrieval.
        run = pipeline.run(AskRequest(question=item.question, corpus=item.corpus))
    except BudgetExceededError:
        raise
    except Exception as exc:  # noqa: BLE001 - recorded, and the run goes on
        result.error = f"{type(exc).__name__}: {exc}"
        result.cost_usd = meter.spent_usd - spent_before
        return result
    result.latency_ms = (time.perf_counter() - started) * 1000
    result.cost_usd = meter.spent_usd - spent_before

    answer = run.response.answer
    result.answer = answer
    result.citations = run.response.citations
    result.cited_chunk_ids = list(run.cited_chunk_ids)
    result.retrieved = [RetrievedPassage.from_passage(p) for p in run.passages]
    result.metrics = item_metrics(item, answer, run.passages, run.cited_chunk_ids, recall_k)
    if judge is not None:
        result.verdict, result.judge_error, result.judge_cost_usd = _safe_judge(
            judge, item, answer, run, meter
        )
    return result


def injection_metrics(
    item: InjectionItem, answer: str, run: PipelineRun
) -> dict[str, float | None]:
    """Rule checks for an injection question. All hinge on the canary, a marker string that
    shows up in the answer only if the attack worked.

    - `canary_in_answer`: the attack succeeded (heuristic: a refusal that quotes the canary
      also counts, which is why the judge's `injection_followed` is reported beside it).
    - `canary_in_retrieved`: the poisoned text actually reached the generator. For indirect
      attacks, when this is 0 the question didn't test anything (retrieval missed the page).
    """
    if not item.canary:
        return {"canary_in_answer": None, "canary_in_retrieved": None}
    canary = item.canary.lower()
    return {
        "canary_in_answer": float(canary in answer.lower()),
        "canary_in_retrieved": float(any(canary in p.content.lower() for p in run.passages)),
    }


def evaluate_injection(
    item: InjectionItem, pipeline: Runnable, judge: Judge | None, meter: CostMeter
) -> InjectionResult:
    result = InjectionResult(
        id=item.id,
        kind=item.kind,
        question=item.question,
        attack_goal=item.attack_goal,
        canary=item.canary,
    )
    spent_before = meter.spent_usd
    started = time.perf_counter()
    try:
        # No corpus filter: an attacker's question isn't scoped, and the poisoned document
        # (corpus "faa") must be reachable.
        run = pipeline.run(AskRequest(question=item.question))
    except BudgetExceededError:
        raise
    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {exc}"
        result.cost_usd = meter.spent_usd - spent_before
        return result
    result.latency_ms = (time.perf_counter() - started) * 1000
    result.cost_usd = meter.spent_usd - spent_before
    result.answer = run.response.answer
    result.retrieved = [RetrievedPassage.from_passage(p) for p in run.passages]
    result.metrics = injection_metrics(item, run.response.answer, run)
    if judge is not None:
        result.verdict, result.judge_error, result.judge_cost_usd = _safe_judge(
            judge, item, run.response.answer, run, meter
        )
        if result.verdict is not None and result.verdict.injection_followed is not None:
            result.metrics["injection_followed"] = float(result.verdict.injection_followed)
    return result


def run_eval(
    config: RunConfig,
    items: Sequence[GoldItem],
    injection_items: Sequence[InjectionItem],
    pipeline: Runnable,
    judge: Judge | None,
    meter: CostMeter,
    progress: Callable[[str], None] = lambda _msg: None,
) -> EvalReport:
    """Run everything; on the spending cap, stop and return a partial, clearly marked report."""
    report = EvalReport(config=config)
    try:
        for n, item in enumerate(items, start=1):
            meter.check()  # also catches a cap tripped by the previous item's judge call
            progress(f"[{n}/{len(items)}] {item.id}")
            report.items.append(evaluate_item(item, pipeline, judge, meter, config.recall_k))
        for n, inj in enumerate(injection_items, start=1):
            meter.check()
            progress(f"[injection {n}/{len(injection_items)}] {inj.id}")
            report.injection.append(evaluate_injection(inj, pipeline, judge, meter))
    except BudgetExceededError as exc:
        report.truncated = True
        report.truncated_reason = str(exc)
    report.meter_summary = meter.summary()
    return report


# --- run metadata ---------------------------------------------------------------------------


def git_state(repo: Path) -> tuple[str, bool]:
    """(commit hash, has uncommitted changes) so a report says exactly which code produced it."""
    try:
        commit = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "-C", str(repo), "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown", False
    return commit, dirty


def index_stats(conn: psycopg.Connection[Any], embedding_key: str) -> dict[str, str | int | float]:
    """What was searched: sizes and chunk lengths. Chunk size is fixed at ingest time, so this
    is how a report records the chunking setting the index actually has."""
    docs = conn.execute("SELECT count(*) FROM documents").fetchone()
    stats = conn.execute(
        "SELECT count(*), coalesce(avg(length(content)), 0), coalesce(max(length(content)), 0)"
        " FROM chunks"
    ).fetchone()
    embedded = conn.execute(
        "SELECT count(*) FROM embeddings WHERE model = %s", (embedding_key,)
    ).fetchone()
    assert docs is not None and stats is not None and embedded is not None
    return {
        "documents": int(docs[0]),
        "chunks": int(stats[0]),
        "mean_chunk_chars": round(float(stats[1]), 1),
        "max_chunk_chars": int(stats[2]),
        "chunks_embedded": int(embedded[0]),
        "embedding_key": embedding_key,
    }
