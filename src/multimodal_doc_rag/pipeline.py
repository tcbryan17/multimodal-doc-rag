"""The real `/ask` pipeline: retrieve → rerank → figures → generate (ADR 0005, 0009, 0010)."""

import re
import time
from dataclasses import replace
from typing import Any

import psycopg

from multimodal_doc_rag.contracts import AskRequest, AskResponse, Citation, TraceStep
from multimodal_doc_rag.fakes import IDK
from multimodal_doc_rag.models.cost import BudgetExceededError
from multimodal_doc_rag.protocols import Embedder, Generator, Reranker
from multimodal_doc_rag.search import fetch_figure_pngs, hybrid_search
from multimodal_doc_rag.types import Passage

SNIPPET_CHARS = 200


def _label(label: str | None, idx: int) -> str:
    # A page with no printed number (e.g. a 10-K cover) is cited by its position instead.
    return label if label is not None else str(idx + 1)


def _snippet(content: str) -> str:
    text = re.sub(r"\s+", " ", content).strip()
    if len(text) <= SNIPPET_CHARS:
        return text
    cut = text[:SNIPPET_CHARS]
    if text[SNIPPET_CHARS] != " ":  # we cut mid-word: back up to the last space
        cut = cut.rsplit(" ", 1)[0] or cut
    return cut.rstrip() + "…"


def _citation(p: Passage) -> Citation:
    start = _label(p.page_start.label, p.page_start.idx)
    end = _label(p.page_end.label, p.page_end.idx)
    return Citation(
        doc=p.doc_title,
        page=start,
        page_end=end if end != start else None,
        snippet=_snippet(p.content),
        # Relative on purpose: the server doesn't know its public origin; the client prefixes
        # its API base. Only figure chunks have an image behind this URL.
        image_url=f"/figures/{p.chunk_id}.png" if p.kind == "figure" else None,
    )


class RagPipeline:
    def __init__(
        self,
        conn: psycopg.Connection[Any],
        *,
        embedder: Embedder,
        reranker: Reranker,
        generator: Generator,
        candidates: int = 30,
        top_k: int = 5,
    ) -> None:
        self._conn = conn
        self._embedder = embedder
        self._reranker = reranker
        self._generator = generator
        self._candidates = candidates
        self._top_k = top_k

    def _rerank(self, question: str, passages: list[Passage]) -> tuple[list[Passage], str]:
        try:
            ranked = self._reranker.rerank(question, [p.content for p in passages], self._top_k)
            kept = [replace(passages[i], score=score) for i, score in ranked[: self._top_k]]
        except BudgetExceededError:
            raise  # a spending cap must stop the run, not quietly degrade it
        except Exception as exc:  # noqa: BLE001 - reranking is an optimisation, never fatal
            # ADR 0009: fall back to hybrid (RRF) order, so a reranker outage costs quality,
            # not availability.
            return passages[: self._top_k], f"rerank skipped: {type(exc).__name__}"
        return kept, f"kept {len(kept)} of {len(passages)}"

    def ask(self, request: AskRequest) -> AskResponse:
        trace: list[TraceStep] = []
        t0 = time.perf_counter()

        def mark(step: str, detail: str) -> None:
            """Close the current stage: ms since the previous mark."""
            nonlocal t0
            now = time.perf_counter()
            trace.append(TraceStep(step=step, detail=detail, ms=int((now - t0) * 1000)))
            t0 = now

        candidates = hybrid_search(
            self._conn,
            request.question,
            self._embedder,
            candidates=self._candidates,
            corpus=request.corpus,
            doc_key=request.doc,
        )
        mark("retrieve", f"{len(candidates)} candidates")

        passages, detail = self._rerank(request.question, candidates)
        mark("rerank", detail)

        figures = fetch_figure_pngs(
            self._conn, [p.chunk_id for p in passages if p.kind == "figure"]
        )
        mark("figures", f"{len(figures)} images")

        if not passages:  # nothing retrieved: don't ask a model to answer from nothing
            mark("generate", "skipped: no passages")
            return AskResponse(answer=IDK, citations=[], trace=trace)
        answer = self._generator.generate(request.question, passages, figures)
        by_id = {p.chunk_id: p for p in passages}
        # Defensive: the generator contract says ids are a subset, but never trust it blindly.
        citations = [_citation(by_id[cid]) for cid in answer.cited_chunk_ids if cid in by_id]
        mark("generate", f"{len(citations)} citations")
        return AskResponse(answer=answer.text, citations=citations, trace=trace)
