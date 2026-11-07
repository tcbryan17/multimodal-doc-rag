"""corpus_ingest without a database: selection, dry-run stats, estimate, preflight, reports."""

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from multimodal_doc_rag.corpus_ingest import (
    CountingDescriber,
    DocResult,
    DocStats,
    DryRunReport,
    FigureSample,
    IngestReport,
    PreflightCheck,
    PreflightReport,
    RetryReport,
    RetryResult,
    analyze_document,
    approx_image_tokens,
    default_parsers,
    estimate_cost,
    parser_for,
    run_preflight,
    scrub,
    select_entries,
    smallest_figure,
    write_report,
)
from multimodal_doc_rag.fakes import CaptionFigureDescriber, PlainTextParser
from multimodal_doc_rag.fetch import ManifestEntry
from multimodal_doc_rag.models.cost import BudgetExceededError, CostMeter, Price
from multimodal_doc_rag.models.openrouter import OpenRouterClient
from multimodal_doc_rag.types import (
    Corpus,
    Element,
    Figure,
    FigureDescription,
    PageRef,
    ParsedDocument,
    SourceInfo,
)

NOW = datetime(2026, 11, 7, 12, 30, 5, tzinfo=UTC)


def entry(key: str, corpus: Corpus = Corpus.FAA, split: str = "dev") -> ManifestEntry:
    return ManifestEntry(
        key, corpus, key.upper(), "https://x", None, None, f"{key}.txt", "s", split
    )


MANIFEST = [
    entry("phak-ch01"),
    entry("phak-ch11", split="heldout"),
    entry("aapl", Corpus.TEN_K),
]


def test_select_entries_filters_and_keeps_heldout() -> None:
    assert [e.doc_key for e in select_entries(MANIFEST)] == ["aapl", "phak-ch01", "phak-ch11"]
    assert [e.doc_key for e in select_entries(MANIFEST, corpus="faa")] == ["phak-ch01", "phak-ch11"]
    assert [e.doc_key for e in select_entries(MANIFEST, only=["aapl"])] == ["aapl"]


def test_select_entries_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="nope"):
        select_entries(MANIFEST, only=["aapl", "nope"])


def test_parser_for_picks_by_suffix() -> None:
    table: Any = {".txt": PlainTextParser()}
    assert parser_for(Path("a.TXT"), table) is table[".txt"]
    with pytest.raises(ValueError, match="no parser"):
        parser_for(Path("a.docx"), table)


def test_default_parsers_cover_the_corpus_suffixes() -> None:
    assert {".htm", ".html", ".pdf"} <= set(default_parsers())


def test_scrub_removes_data_dir_and_truncates(tmp_path: Path) -> None:
    out = scrub(f"bad file {tmp_path}/x.pdf\nsecond line " + "z" * 500, tmp_path)
    assert str(tmp_path) not in out and "<data>/x.pdf" in out
    assert len(out) == 300 and "\n" not in out


# --- dry-run statistics and estimate -------------------------------------------------------------


def fig(w: int = 750, h: int = 100) -> Figure:
    return Figure("1-1", "Figure 1-1. Chart", b"png", w, h)


def parsed_doc() -> ParsedDocument:
    src = entry("d").to_source_info()
    els = (
        Element("text", "Intro paragraph.", PageRef(0, "1"), ("Ch 1",)),
        Element("text", "Cover text", PageRef(1, None), ("Ch 1",)),
        Element("figure", "Figure 1-1. Chart", PageRef(1, "2"), ("Ch 1",), fig()),
        Element("table", "| a |\n|---|\n| 1 |", PageRef(2, "3"), ("Ch 2",)),
    )
    return ParsedDocument(src, "sha", 3, els)


def test_analyze_document_counts() -> None:
    s = analyze_document(entry("d"), parsed_doc(), seconds=1.234)
    assert s.pages == 3 and s.figures == 1 and s.unlabelled_elements == 1
    assert s.elements_by_kind == {"text": 2, "figure": 1, "table": 1}
    assert s.chunks_by_kind["figure"] == 1 and s.chunks_by_kind["table"] == 1
    assert s.embed_tokens > s.content_tokens > 0  # headers are embedded too
    assert s.figure_image_tokens == 100  # 750*100/750
    assert s.seconds == 1.2 and s.split == "dev"


def test_approx_image_tokens_is_capped() -> None:
    assert approx_image_tokens(750, 750) == 750
    assert approx_image_tokens(4000, 4000) == 1600


def stats(figures: int = 10, embed_tokens: int = 1_000_000, image_tokens: int = 10_000) -> DocStats:
    return DocStats(
        "d", "faa", "dev", "d.pdf", 5, {}, {}, 0, embed_tokens, 0, figures, image_tokens, 0.0
    )


PRICES = {"emb": Price(0.02), "vis": Price(0.15, 0.75)}


def test_estimate_cost_arithmetic() -> None:
    est = estimate_cost([stats()], embedding_model="emb", vision_model="vis", prices=PRICES)
    assert est.embed_tokens == 1_000_000 + 10 * 400
    assert est.embed_usd == pytest.approx((1_004_000) * 0.02 / 1e6, abs=1e-4)
    assert est.vision_input_tokens == 10_000 + 10 * 500
    assert est.vision_output_tokens == 4000
    assert est.vision_usd == pytest.approx((15_000 * 0.15 + 4000 * 0.75) / 1e6, abs=1e-4)
    assert est.total_usd == pytest.approx(est.embed_usd + est.vision_usd, abs=1e-4)
    assert est.suggested_credit_limit_usd >= 1.0
    assert any("capped" in a for a in est.assumptions)


def test_estimate_flags_missing_price() -> None:
    est = estimate_cost([stats()], embedding_model="emb", vision_model="??", prices=PRICES)
    assert any("NO PRICE for ??" in a for a in est.assumptions)


def test_dry_run_report_renders_everything() -> None:
    est = estimate_cost([stats()], embedding_model="emb", vision_model="vis", prices=PRICES)
    report = DryRunReport("t", [stats()], est, {"bad": "ValueError: boom"})
    md = report.markdown()
    for needle in (
        "| d | faa | dev | 5 |",
        "Suggested OpenRouter credit limit",
        "Assumptions",
        "`bad`: ValueError",
    ):
        assert needle in md
    assert dataclasses.asdict(report)["docs"][0]["doc_key"] == "d"


# --- smallest figure + counting wrapper -----------------------------------------------------------


class FigParser:
    """Reads whitespace-separated 'WxH' pairs from the file, one figure each."""

    def parse(self, path: Path, source: SourceInfo) -> ParsedDocument:
        els = []
        for i, dims in enumerate(path.read_text().split()):
            w, h = map(int, dims.split("x"))
            f = Figure(str(i), f"cap {i}", b"png", w, h)
            els.append(Element("figure", f.caption, PageRef(0, "1"), (), f))
        return ParsedDocument(source, "sha", 1, tuple(els))


def test_smallest_figure_samples_first_docs_with_figures(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("")  # no figures: not counted toward max_docs
    (tmp_path / "b.txt").write_text("500x500 20x30")
    (tmp_path / "c.txt").write_text("5x5")
    (tmp_path / "d.txt").write_text("1x1")
    entries = [entry(k) for k in "abcd"]
    table: Any = {".txt": FigParser()}
    got = smallest_figure(entries, tmp_path, table, max_docs=2)
    assert got is not None and (got.doc_key, got.figure.width) == ("c", 5)  # d is never parsed
    assert smallest_figure([entry("a")], tmp_path, table) is None


class Flaky:
    def __init__(self, exc: Exception | None) -> None:
        self.exc = exc

    def describe(self, png: bytes, caption: str, context: str) -> FigureDescription:
        if self.exc:
            raise self.exc
        return FigureDescription(True, "d")


def test_counting_describer_counts_and_reraises() -> None:
    lines: list[str] = []
    ok = CountingDescriber(Flaky(None), log=lines.append, every=2)
    ok.describe(b"", "", "")
    ok.describe(b"", "", "")
    assert ok.described == 2 and ok.failed == 0 and lines == ["    2 figures done (0 failed)"]
    bad = CountingDescriber(Flaky(RuntimeError("x")), log=lines.append)
    with pytest.raises(RuntimeError):
        bad.describe(b"", "", "")
    assert bad.failed == 1
    budget = CountingDescriber(Flaky(BudgetExceededError("cap")), log=lines.append)
    with pytest.raises(BudgetExceededError):
        budget.describe(b"", "", "")
    assert budget.failed == 0  # running out of money is not a figure failure


def test_counting_describer_wraps_the_fake_describer() -> None:
    counter = CountingDescriber(CaptionFigureDescriber(), log=lambda _: None)
    assert counter.describe(b"", "Figure 1. x", "").informational


# --- preflight (httpx2.MockTransport, no network) -------------------------------------------------

GOOD_JSON = '{"informational": true, "description": "d"}'
CHAT_USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001}


def preflight_client(
    *, raw_dim: int = 2048, rerank_ok: bool = True, chat_text: str = GOOD_JSON,
    bad_embed: bool = False,
) -> OpenRouterClient:  # fmt: skip
    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith("/embeddings"):
            vec = [0.0] * (8 if bad_embed else raw_dim)
            vec[0] = 3.0  # not unit length: the adapter must normalise it
            return httpx2.Response(200, json={"data": [{"index": 0, "embedding": vec}]})
        if path.endswith("/rerank"):
            if not rerank_ok:
                return httpx2.Response(400, json={"error": {"message": "no such model"}})
            results = [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.1},
                {"index": 2, "relevance_score": 0.2},
            ]
            return httpx2.Response(200, json={"results": results})
        body = {"choices": [{"message": {"content": chat_text}}], "usage": CHAT_USAGE}
        return httpx2.Response(200, json=body)

    return OpenRouterClient(
        SecretStr("sk-test"), "https://example.test/api/v1", 5.0,
        transport=httpx2.MockTransport(handler), sleep=lambda _: None,
        meter=CostMeter(1.0, prices=PRICES),
    )  # fmt: skip


def run(client: OpenRouterClient, with_figure: bool = True) -> PreflightReport:
    return run_preflight(
        client, embedding_model="emb", embedding_dim=1024, rerank_model="rr", vision_model="vis",
        sample=FigureSample("d", fig()) if with_figure else None, now=lambda: NOW,
    )  # fmt: skip


def by_name(report: PreflightReport) -> dict[str, PreflightCheck]:
    return {c.name: c for c in report.checks}


def test_preflight_all_pass_and_reports_provider_ignoring_dimensions() -> None:
    report = run(preflight_client(raw_dim=2048))
    checks = by_name(report)
    assert report.ok
    assert checks["embeddings"].status == "pass" and "IGNORED" in checks["embeddings"].detail
    assert checks["rerank"].status == "pass" and checks["vision"].status == "pass"
    cost = checks["cost reporting"].detail
    # only chat reported a price; embed/rerank responses had no usage, so they were unpriced
    assert "vision: reported" in cost and "embeddings: unpriced" in cost


def test_preflight_notes_honoured_dimensions() -> None:
    report = run(preflight_client(raw_dim=1024))
    assert "honoured" in by_name(report)["embeddings"].detail


def test_preflight_embedding_failure_aborts() -> None:
    report = run(preflight_client(bad_embed=True))
    assert not report.ok and by_name(report)["embeddings"].status == "fail"
    assert "FAILED" in report.markdown()


def test_preflight_rerank_failure_is_a_loud_warning_not_a_failure() -> None:
    report = run(preflight_client(rerank_ok=False))
    assert report.ok
    rerank = by_name(report)["rerank"]
    assert rerank.status == "warn" and "WARNING" in rerank.detail and "RRF" in rerank.detail


def test_preflight_vision_failure_aborts() -> None:
    report = run(preflight_client(chat_text="not json at all"))
    assert not report.ok and by_name(report)["vision"].status == "fail"


def test_preflight_without_a_figure_warns() -> None:
    report = run(preflight_client(), with_figure=False)
    assert report.ok and by_name(report)["vision"].status == "warn"


def test_preflight_propagates_budget_exhaustion() -> None:
    client = preflight_client()
    assert client.meter is not None
    client.meter.spent_usd = 5.0
    with pytest.raises(BudgetExceededError):
        run(client)


def test_preflight_requires_a_meter() -> None:
    client = preflight_client()
    client.meter = None
    with pytest.raises(ValueError, match="CostMeter"):
        run(client)


# --- report rendering and writing -----------------------------------------------------------------


def test_ingest_report_markdown() -> None:
    results = [
        DocResult("a", "dev", "ingested", 3.2, 4, 3, 1, failures=["a#chunk4: RuntimeError: x"]),
        DocResult("b", "heldout", "skipped-existing"),
        DocResult("c", "dev", "failed", error="budget: cap"),
        DocResult("d", "dev", "not-reached"),
    ]
    md = IngestReport("t", results, "$0.1 of $3", budget_exceeded=True).markdown()
    assert "STOPPED" in md and "1 document(s) written" in md and "1 skipped" in md
    assert "| a | dev | ingested | 4 | 3 | 1 |" in md and "heldout" in md
    assert "`a` a#chunk4: RuntimeError: x" in md and "Spend: $0.1 of $3" in md
    assert "not-reached" in md


def test_ingest_report_without_failures() -> None:
    assert "None." in IngestReport("t", [DocResult("a", "dev", "ingested")], "s").markdown()


def test_retry_report_markdown() -> None:
    results = [RetryResult("a#chunk1", "resolved"), RetryResult("b#chunk2", "orphaned", "gone")]
    md = RetryReport("t", results, "s").markdown()
    assert "a#chunk1" in md and "orphaned" in md
    assert "No unresolved" in RetryReport("t", [], "s").markdown()


def test_write_report_names_files_by_utc_timestamp_and_mode(tmp_path: Path) -> None:
    report = IngestReport("t", [DocResult("a", "dev", "ingested")], "s")
    md, js = write_report(report, tmp_path / "reports" / "ingest", NOW)
    assert md.name == "20261107T123005Z-ingest.md" and js.name == "20261107T123005Z-ingest.json"
    data = json.loads(js.read_text())
    assert data["results"][0]["doc_key"] == "a" and "sk-" not in js.read_text()
    assert md.read_text().startswith("# Ingest run")
