"""Cost meter tests: the cap must fail closed (ADR 0011: every eval run has a cost cap)."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx2
import psycopg
import pytest
from pydantic import SecretStr

from multimodal_doc_rag.contracts import AskRequest
from multimodal_doc_rag.fakes import CaptionFigureDescriber, HashingEmbedder, PlainTextParser
from multimodal_doc_rag.ingest import ingest_document
from multimodal_doc_rag.models.cost import BudgetExceededError, CostMeter, Price
from multimodal_doc_rag.models.openrouter import OpenRouterClient
from multimodal_doc_rag.parsing.handbook_pdf import HandbookPdfParser
from multimodal_doc_rag.pipeline import RagPipeline
from multimodal_doc_rag.types import Corpus, FigureDescription, GeneratedAnswer, Passage, SourceInfo

Conn = psycopg.Connection[Any]


def test_reported_cost_is_preferred() -> None:
    meter = CostMeter(cap_usd=1.0, prices={"m": Price(1000.0, 1000.0)})
    charged = meter.record("m", {"cost": 0.002, "prompt_tokens": 10, "completion_tokens": 10})
    assert charged == pytest.approx(0.002)
    assert (meter.reported_calls, meter.estimated_calls, meter.unpriced_calls) == (1, 0, 0)


def test_missing_cost_is_estimated_from_tokens() -> None:
    meter = CostMeter(cap_usd=1.0, prices={"m": Price(input_per_m=2.0, output_per_m=10.0)})
    charged = meter.record("m", {"prompt_tokens": 1_000, "completion_tokens": 100})
    assert charged == pytest.approx((1_000 * 2.0 + 100 * 10.0) / 1_000_000)
    assert meter.estimated_calls == 1


@pytest.mark.parametrize(
    "model, usage",
    [
        ("unknown/model", {"prompt_tokens": 5}),  # no price for this model
        ("m", None),  # no usage at all
        ("m", {"cost": "free"}),  # garbage cost
        ("m", {"cost": True}),  # bool is an int subclass: must not count as $1
    ],
)
def test_unknown_price_charges_the_pessimistic_flat_rate(model: str, usage: object) -> None:
    meter = CostMeter(cap_usd=1.0, prices={"m": Price(1.0)}, unpriced_call_usd=0.01)
    assert meter.record(model, usage) == pytest.approx(0.01)
    assert meter.unpriced_calls == 1


def test_check_raises_once_cap_reached() -> None:
    meter = CostMeter(cap_usd=0.01)
    meter.check()  # nothing spent yet
    meter.record("m", {"cost": 0.01})
    with pytest.raises(BudgetExceededError, match="spending cap reached"):
        meter.check()


def chat_response(_: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(
        200, json={"choices": [{"message": {"content": "hi"}}], "usage": {"cost": 0.004}}
    )


def make_client(meter: CostMeter, requests: list[httpx2.Request]) -> OpenRouterClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return chat_response(request)

    return OpenRouterClient(
        SecretStr("k"), "https://x.test/api/v1", 5.0, transport=httpx2.MockTransport(handler),
        meter=meter,
    )  # fmt: skip


def test_client_charges_meter_and_stops_before_overspending() -> None:
    meter = CostMeter(cap_usd=0.01)
    requests: list[httpx2.Request] = []
    client = make_client(meter, requests)
    for _ in range(3):  # 3 × $0.004 = $0.012: the third call crosses the cap
        client.chat("m", [], max_tokens=5)
    assert meter.spent_usd == pytest.approx(0.012)
    with pytest.raises(BudgetExceededError):
        client.chat("m", [], max_tokens=5)
    assert len(requests) == 3  # the fourth request was never sent


def test_chat_asks_openrouter_to_report_usage() -> None:
    requests: list[httpx2.Request] = []
    make_client(CostMeter(cap_usd=1.0), requests).chat("m", [], max_tokens=5)
    assert b'"usage":{"include":true}' in requests[0].content.replace(b" ", b"")


# --- degrade paths must not swallow a budget stop -------------------------------------------


class BrokeDescriber:
    def describe(self, png: bytes, caption: str, context: str) -> FigureDescription:
        raise BudgetExceededError("cap")


class BrokeReranker:
    def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[tuple[int, float]]:
        raise BudgetExceededError("cap")


class NeverGenerator:
    def generate(
        self, question: str, passages: Sequence[Passage], figures: Mapping[int, bytes]
    ) -> GeneratedAnswer:
        raise AssertionError("must not be reached")


@pytest.mark.db
def test_ingest_stops_on_budget_instead_of_degrading(
    db_conn: Conn, mini_handbook_pdf: Path
) -> None:
    src = SourceInfo("mini", Corpus.FAA, "Mini", "https://example.test/mini.pdf")
    with pytest.raises(BudgetExceededError):
        ingest_document(
            db_conn, HandbookPdfParser(), mini_handbook_pdf, src,
            embedder=HashingEmbedder(), describer=BrokeDescriber(),
        )  # fmt: skip


@pytest.mark.db
def test_pipeline_rerank_does_not_swallow_budget(db_conn: Conn, tmp_path: Path) -> None:
    doc = tmp_path / "d.txt"
    doc.write_text("# Fuel\n\nAvgas is blue.", encoding="utf-8")
    src = SourceInfo("d", Corpus.FAA, "D", "https://example.test/d")
    embedder = HashingEmbedder()
    ingest_document(
        db_conn, PlainTextParser(), doc, src, embedder=embedder, describer=CaptionFigureDescriber()
    )
    pipeline = RagPipeline(
        db_conn, embedder=embedder, reranker=BrokeReranker(), generator=NeverGenerator()
    )
    with pytest.raises(BudgetExceededError):
        pipeline.ask(AskRequest(question="What colour is avgas?"))
