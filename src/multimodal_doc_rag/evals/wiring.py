"""Builds the real components for an eval run (and the cost meter that caps it)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import psycopg

from multimodal_doc_rag.config import Settings
from multimodal_doc_rag.evals.judge import Judge, OpenRouterJudge
from multimodal_doc_rag.models.adapters import (
    OpenRouterEmbedder,
    OpenRouterGenerator,
    OpenRouterReranker,
)
from multimodal_doc_rag.models.cost import CostMeter, Price
from multimodal_doc_rag.models.openrouter import OpenRouterClient
from multimodal_doc_rag.pipeline import RagPipeline

# The generators ADR 0009 plans to compare. Others are allowed (the harness is general) but
# we warn, since a typo'd model id would otherwise only show up as a provider error.
ALLOWED_GENERATORS = (
    "anthropic/claude-haiku-5.5",
    "google/gemma-4-26b-a4b-it",
    "qwen/qwen3.6-35b-a3b",
)


def generator_warning(model: str) -> str | None:
    if model in ALLOWED_GENERATORS:
        return None
    return (
        f"generator {model!r} is not one of the ADR 0009 comparison models "
        f"({', '.join(ALLOWED_GENERATORS)}); continuing anyway"
    )


class PassThroughReranker:
    """`--no-rerank`: keep the hybrid-search (RRF) order, so a run measures retrieval without
    the reranker (ADR 0011 compares reranking on vs off)."""

    def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[tuple[int, float]]:
        n = min(top_n, len(documents))
        return [(i, float(n - i)) for i in range(n)]  # descending, so "best first" holds


def build_meter(settings: Settings, cap_usd: float) -> CostMeter:
    return CostMeter(
        cap_usd=cap_usd,
        prices={m: Price(i, o) for m, (i, o) in settings.model_prices.items()},
        unpriced_call_usd=settings.unpriced_call_usd,
    )


@dataclass
class EvalComponents:
    pipeline: RagPipeline
    judge: Judge | None
    meter: CostMeter
    client: OpenRouterClient


def build_components(
    settings: Settings,
    conn: psycopg.Connection[Any],
    *,
    generator_model: str,
    rerank: bool,
    top_k: int,
    candidates: int,
    budget_usd: float,
    use_judge: bool,
    client: OpenRouterClient | None = None,
) -> EvalComponents:
    """One client (hence one meter) behind the embedder, reranker, generator and judge, so the
    cap covers the whole run.

    The judge is built FIRST so a missing JUDGE_MODEL fails before any money is spent.
    """
    meter = build_meter(settings, budget_usd)
    client = client or OpenRouterClient.from_settings(meter=meter)
    client.meter = meter
    judge: Judge | None = None
    if use_judge:
        judge = OpenRouterJudge(client, settings.judge_model, generator_model)
    pipeline = RagPipeline(
        conn,
        embedder=OpenRouterEmbedder.from_settings(settings, client),
        reranker=OpenRouterReranker(client, settings.rerank_model)
        if rerank
        else PassThroughReranker(),
        generator=OpenRouterGenerator(client, generator_model),
        candidates=candidates,
        top_k=top_k,
    )
    return EvalComponents(pipeline=pipeline, judge=judge, meter=meter, client=client)
