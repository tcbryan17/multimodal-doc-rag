"""Corpus-level ingestion: dry run, preflight canary, real ingest, replace, retry (build-plan 14).

`ingest.py` ingests ONE file; this module drives it over the whole manifest, safely:

- DRY RUN parses and chunks only (no database, no model calls) and estimates what a real run
  would cost, so the owner can size the OpenRouter key's credit limit before adding money.
- PREFLIGHT spends a few cents on one call of each kind, to verify the behaviours we could not
  check without a key BEFORE committing to ~560 vision calls.
- REAL INGEST commits one transaction per document: a crash or an exhausted budget leaves only
  whole documents behind, never a half-indexed one.
- REPLACE exists because `document_exists()` keys on the source bytes' hash: after a parser fix
  the bytes are unchanged, so without it re-ingesting would be a silent no-op.
- RETRY re-describes figures whose vision call failed (ADR 0008 degrades them to caption-only).

Everything takes its dependencies (connection, adapters, parsers, clock, logger) as arguments,
so tests drive it with fakes. The CLI in `scripts/ingest_corpus.py` is only argument parsing.
"""

import dataclasses
import hashlib
import json
import math
import re
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Protocol

import psycopg

from multimodal_doc_rag.chunking import chunk_document, count_tokens
from multimodal_doc_rag.db.repository import (
    delete_document,
    get_document_sha,
    insert_embeddings,
)
from multimodal_doc_rag.fetch import ManifestEntry
from multimodal_doc_rag.ingest import ingest_document
from multimodal_doc_rag.models.adapters import (
    OpenRouterEmbedder,
    OpenRouterFigureDescriber,
    OpenRouterReranker,
)
from multimodal_doc_rag.models.cost import BudgetExceededError, CostMeter, Price
from multimodal_doc_rag.models.openrouter import OpenRouterClient
from multimodal_doc_rag.protocols import Embedder, FigureDescriber, Parser
from multimodal_doc_rag.types import Figure, ParsedDocument, embed_text

Conn = psycopg.Connection[Any]
Log = Callable[[str], None]

# --- cost-estimate assumptions (stated verbatim in the dry-run report) -------------------------

VISION_PROMPT_TOKENS = 500  # DESCRIBE_PROMPT plus caption and surrounding-text context
VISION_OUTPUT_TOKENS = 400  # a dense description; the adapter allows up to 700
DESCRIPTION_EMBED_TOKENS = 400  # the description is prepended to the chunk, then embedded
IMAGE_PIXELS_PER_TOKEN = 750  # Anthropic's rule of thumb: tokens ~ width * height / 750
IMAGE_TOKEN_CAP = 1600  # Anthropic downscales big images (long edge ~1568 px), capping the cost


def approx_image_tokens(width: int, height: int) -> int:
    return min(math.ceil(width * height / IMAGE_PIXELS_PER_TOKEN), IMAGE_TOKEN_CAP)


def parser_for(path: Path, parsers: Mapping[str, Parser] | None = None) -> Parser:
    """Pick the parser by file suffix (the manifest has one source file per document)."""
    table = parsers if parsers is not None else default_parsers()
    suffix = path.suffix.lower()
    if suffix not in table:
        raise ValueError(f"no parser for {path.name!r} (suffix {suffix!r})")
    return table[suffix]


def default_parsers() -> dict[str, Parser]:
    # Imported here so merely importing this module doesn't load PyMuPDF/BeautifulSoup.
    from multimodal_doc_rag.parsing.edgar import EdgarHtmlParser
    from multimodal_doc_rag.parsing.handbook_pdf import HandbookPdfParser

    edgar, pdf = EdgarHtmlParser(), HandbookPdfParser()
    return {".htm": edgar, ".html": edgar, ".pdf": pdf}


def select_entries(
    manifest: Sequence[ManifestEntry],
    *,
    only: Sequence[str] | None = None,
    corpus: str | None = None,
) -> list[ManifestEntry]:
    """Filter the manifest. Held-out documents are INCLUDED: the held-out eval must be able
    to search them. Unknown keys are an error (a typo should not silently ingest nothing)."""
    if only:
        known = {e.doc_key for e in manifest}
        unknown = sorted(set(only) - known)
        if unknown:
            raise ValueError(f"not in the manifest: {', '.join(unknown)}")
    chosen = [
        e
        for e in manifest
        if (not only or e.doc_key in only) and (corpus is None or e.corpus.value == corpus)
    ]
    return sorted(chosen, key=lambda e: e.doc_key)


def scrub(text: str, data_dir: Path) -> str:
    """Keep local paths and long messages out of reports (they are committed)."""
    return " ".join(
        text.replace(str(data_dir.resolve()), "<data>").replace(str(data_dir), "<data>").split()
    )[:300]


# --- reports (pure data + pure rendering) --------------------------------------------------------


class Report(Protocol):
    mode: ClassVar[str]

    def markdown(self) -> str: ...


def report_json(report: Any) -> str:
    return json.dumps(dataclasses.asdict(report), indent=2, sort_keys=True) + "\n"


def write_report(report: Report, directory: Path, now: datetime) -> tuple[Path, Path]:
    """Write reports/ingest/<UTC timestamp>-<mode>.md and .json; returns both paths."""
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{now.astimezone(UTC):%Y%m%dT%H%M%SZ}-{report.mode}"
    md, js = directory / f"{stem}.md", directory / f"{stem}.json"
    md.write_text(report.markdown(), encoding="utf-8")
    js.write_text(report_json(report), encoding="utf-8")
    return md, js


def _table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _kinds(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none"


# Dry run -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DocStats:
    doc_key: str
    corpus: str
    split: str
    path: str  # relative to the data dir
    pages: int
    elements_by_kind: dict[str, int]
    chunks_by_kind: dict[str, int]
    content_tokens: int  # approx tokens of the stored chunk text
    embed_tokens: int  # approx tokens actually embedded (header + content)
    unlabelled_elements: int  # elements whose page has no printed label
    figures: int
    figure_image_tokens: int  # estimated vision-input tokens for this document's images
    seconds: float


def analyze_document(
    entry: ManifestEntry,
    parsed: ParsedDocument,
    *,
    max_tokens: int = 500,
    seconds: float = 0.0,
) -> DocStats:
    chunks = chunk_document(parsed, max_tokens=max_tokens)
    figures = [e.figure for e in parsed.elements if e.figure is not None]
    return DocStats(
        doc_key=entry.doc_key,
        corpus=entry.corpus.value,
        split=entry.split,
        path=entry.path,
        pages=parsed.page_count,
        elements_by_kind=dict(Counter(e.kind for e in parsed.elements)),
        chunks_by_kind=dict(Counter(c.kind for c in chunks)),
        content_tokens=sum(count_tokens(c.content) for c in chunks),
        embed_tokens=sum(count_tokens(c.embed_text) for c in chunks),
        unlabelled_elements=sum(1 for e in parsed.elements if e.page.label is None),
        figures=len(figures),
        figure_image_tokens=sum(approx_image_tokens(f.width, f.height) for f in figures),
        seconds=round(seconds, 1),
    )


@dataclass(frozen=True)
class CostEstimate:
    embedding_model: str
    vision_model: str
    embed_tokens: int
    embed_usd: float
    figures: int
    vision_input_tokens: int
    vision_output_tokens: int
    vision_usd: float
    total_usd: float
    suggested_credit_limit_usd: float
    assumptions: list[str]


def estimate_cost(
    stats: Sequence[DocStats],
    *,
    embedding_model: str,
    vision_model: str,
    prices: Mapping[str, Price],
) -> CostEstimate:
    figures = sum(s.figures for s in stats)
    embed_tokens = sum(s.embed_tokens for s in stats) + figures * DESCRIPTION_EMBED_TOKENS
    vision_in = sum(s.figure_image_tokens for s in stats) + figures * VISION_PROMPT_TOKENS
    vision_out = figures * VISION_OUTPUT_TOKENS
    notes: list[str] = []

    def price(model: str) -> Price:
        found = prices.get(model)
        if found is None:
            notes.append(f"NO PRICE for {model}: add it to MODEL_PRICES; its cost is counted as 0")
            return Price(0.0, 0.0)
        return found

    p_embed, p_vision = price(embedding_model), price(vision_model)
    embed_usd = embed_tokens * p_embed.input_per_m / 1e6
    vision_usd = (vision_in * p_vision.input_per_m + vision_out * p_vision.output_per_m) / 1e6
    total = embed_usd + vision_usd
    notes += [
        "Embedding tokens = approx tokens (chars / 4) of each chunk's context header + content, "
        f"plus {DESCRIPTION_EMBED_TOKENS} per figure for the description that gets prepended.",
        f"Every figure is assumed to get one vision call: ~{VISION_PROMPT_TOKENS} prompt tokens "
        f"+ image tokens + ~{VISION_OUTPUT_TOKENS} output tokens. Decorative figures cost the "
        "same call, so none are assumed to be skipped.",
        f"Image tokens ~ width x height / {IMAGE_PIXELS_PER_TOKEN} (Anthropic's rule of thumb), "
        f"capped at {IMAGE_TOKEN_CAP} per image because large images are downscaled.",
        "Prices come from MODEL_PRICES (USD per million tokens), rounded up when set; if "
        "OpenRouter reports the real `usage.cost` the actual bill will differ.",
        "Chunk counts assume the default 500-token chunk size. Retries, preflight and failed "
        "calls are not included: the suggested credit limit is 2x the estimate, minimum $1.",
    ]
    return CostEstimate(
        embedding_model=embedding_model,
        vision_model=vision_model,
        embed_tokens=embed_tokens,
        embed_usd=round(embed_usd, 4),
        figures=figures,
        vision_input_tokens=vision_in,
        vision_output_tokens=vision_out,
        vision_usd=round(vision_usd, 4),
        total_usd=round(total, 4),
        suggested_credit_limit_usd=max(1.0, math.ceil(total * 2 * 10) / 10),
        assumptions=notes,
    )


@dataclass(frozen=True)
class DryRunReport:
    mode: ClassVar[str] = "dry-run"
    generated_at: str
    docs: list[DocStats]
    estimate: CostEstimate
    failed: dict[str, str] = field(default_factory=dict)  # doc_key -> parse error

    def markdown(self) -> str:
        e = self.estimate
        rows = [
            (
                d.doc_key,
                d.corpus,
                d.split,
                d.pages,
                _kinds(d.elements_by_kind),
                _kinds(d.chunks_by_kind),
                f"{d.content_tokens:,}",
                d.unlabelled_elements,
                d.figures,
                d.seconds,
            )
            for d in self.docs
        ]
        out = [
            "# Ingest dry run",
            "",
            f"Generated {self.generated_at}. Parsed and chunked only: no database, no model calls.",
            "",
            "## Per-document stats",
            "",
            _table(
                [
                    "doc",
                    "corpus",
                    "split",
                    "pages",
                    "elements",
                    "chunks",
                    "~tokens",
                    "no page label",
                    "figures",
                    "parse s",
                ],
                rows,
            ),
            "",
            f"Totals: {sum(d.pages for d in self.docs)} pages, "
            f"{sum(sum(d.chunks_by_kind.values()) for d in self.docs)} chunks, "
            f"{sum(d.figures for d in self.docs)} figures, "
            f"{sum(d.unlabelled_elements for d in self.docs)} elements without a printed page "
            "label.",
            "",
        ]
        if self.failed:
            out += ["## Documents that failed to parse", ""]
            out += [f"- `{k}`: {v}" for k, v in sorted(self.failed.items())]
            out.append("")
        out += [
            "## Cost estimate",
            "",
            _table(
                ["part", "model", "quantity", "USD"],
                [
                    ("embeddings", e.embedding_model, f"{e.embed_tokens:,} tokens", e.embed_usd),
                    (
                        "figure descriptions",
                        e.vision_model,
                        f"{e.figures:,} calls ({e.vision_input_tokens:,} in / "
                        f"{e.vision_output_tokens:,} out tokens)",
                        e.vision_usd,
                    ),
                    ("**total**", "", "", f"**{e.total_usd}**"),
                ],
            ),
            "",
            "Suggested OpenRouter credit limit for the key: "
            f"**${e.suggested_credit_limit_usd:.2f}**.",
            "",
            "### Assumptions",
            "",
            *[f"- {a}" for a in e.assumptions],
            "",
        ]
        return "\n".join(out)


# Preflight -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str  # "pass" | "warn" | "fail" | "info"
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    mode: ClassVar[str] = "preflight"
    generated_at: str
    checks: list[PreflightCheck]
    meter_summary: str

    @property
    def ok(self) -> bool:
        return all(c.status != "fail" for c in self.checks)

    def markdown(self) -> str:
        verdict = "PASSED" if self.ok else "FAILED: do not start the real ingest"
        return "\n".join(
            [
                "# Ingest preflight",
                "",
                f"Generated {self.generated_at}. Result: **{verdict}**.",
                "",
                _table(
                    ["check", "status", "detail"],
                    [(c.name, c.status.upper(), c.detail) for c in self.checks],
                ),
                "",
                f"Spend: {self.meter_summary}",
                "",
            ]
        )


@dataclass(frozen=True)
class FigureSample:
    doc_key: str
    figure: Figure


def smallest_figure(
    entries: Sequence[ManifestEntry],
    data_dir: Path,
    parsers: Mapping[str, Parser] | None = None,
    *,
    max_docs: int = 2,
) -> FigureSample | None:
    """The smallest figure (by pixels) from the first `max_docs` selected documents that have
    one. Scanning the whole corpus would cost the ~4 minutes of parsing we are trying to save
    before the canary, so this samples; the canary only needs a real image, not THE smallest."""
    best: FigureSample | None = None
    seen = 0
    for entry in entries:
        path = data_dir / entry.path
        parsed = parser_for(path, parsers).parse(path, entry.to_source_info())
        figures = [e.figure for e in parsed.elements if e.figure is not None]
        if not figures:
            continue
        seen += 1
        small = min(figures, key=lambda f: f.width * f.height)
        if best is None or small.width * small.height < best.figure.width * best.figure.height:
            best = FigureSample(entry.doc_key, small)
        if seen >= max_docs:
            break
    return best


def _cost_source(meter: CostMeter, before: tuple[int, int, int]) -> str:
    after = (meter.reported_calls, meter.estimated_calls, meter.unpriced_calls)
    if after[0] > before[0]:
        return "reported"
    if after[1] > before[1]:
        return "estimated"
    return "unpriced" if after[2] > before[2] else "no call recorded"


def _meter_state(meter: CostMeter) -> tuple[int, int, int]:
    return (meter.reported_calls, meter.estimated_calls, meter.unpriced_calls)


def run_preflight(
    client: OpenRouterClient,
    *,
    embedding_model: str,
    embedding_dim: int,
    rerank_model: str,
    vision_model: str,
    sample: FigureSample | None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> PreflightReport:
    """One call of each kind. A BudgetExceededError propagates: it is not a check result."""
    meter = client.meter
    if meter is None:
        raise ValueError("preflight needs a client with a CostMeter (it reports cost sources)")
    checks: list[PreflightCheck] = []

    # (a) embeddings: the dimension we store, unit length, and whether `dimensions` was honoured.
    before = _meter_state(meter)
    try:
        raw = client.embed(embedding_model, ["preflight canary text"], dimensions=embedding_dim)
        honoured = len(raw[0]) == embedding_dim
        vector = OpenRouterEmbedder(client, embedding_model, embedding_dim).embed_documents(
            ["preflight canary text"]
        )[0]
        norm = math.sqrt(sum(x * x for x in vector))
        if len(vector) == embedding_dim and math.isclose(norm, 1.0, rel_tol=1e-6):
            checks.append(
                PreflightCheck(
                    "embeddings",
                    "pass",
                    f"stored dim {len(vector)}, unit length. Provider "
                    + (
                        "honoured `dimensions`"
                        if honoured
                        else f"IGNORED `dimensions` (raw length {len(raw[0])}); we truncate and "
                        "re-normalise ourselves"
                    ),
                )
            )
        else:
            checks.append(
                PreflightCheck("embeddings", "fail", f"dim {len(vector)}, norm {norm:.4f}")
            )
    except BudgetExceededError:
        raise
    except Exception as exc:  # noqa: BLE001 - any failure here is a verdict, not a crash
        checks.append(PreflightCheck("embeddings", "fail", f"{type(exc).__name__}: {exc}"))
    embed_cost = _cost_source(meter, before)

    # (b) rerank: a failure is only a warning, because the pipeline falls back to RRF order.
    before = _meter_state(meter)
    docs = [
        "Revenue grew 6%.",
        "The altimeter measures altitude.",
        "A stall is an aerodynamic loss of lift.",
    ]
    try:
        ranked = OpenRouterReranker(client, rerank_model).rerank(
            "what does an altimeter measure", docs, 3
        )
        indices = [i for i, _ in ranked]
        if (
            len(set(indices)) == len(indices)
            and all(0 <= i < len(docs) for i in indices)
            and ranked
        ):
            checks.append(
                PreflightCheck("rerank", "pass", f"valid indices/scores, best = doc {indices[0]}")
            )
        else:
            checks.append(
                PreflightCheck(
                    "rerank",
                    "warn",
                    f"WARNING: invalid result {ranked!r}; /ask will fall back to RRF order",
                )
            )
    except BudgetExceededError:
        raise
    except Exception as exc:  # noqa: BLE001
        checks.append(
            PreflightCheck(
                "rerank",
                "warn",
                f"WARNING: {type(exc).__name__}: {exc}. /ask will fall back to hybrid (RRF) order "
                "without reranking; ingest can still proceed",
            )
        )
    rerank_cost = _cost_source(meter, before)

    # (c) vision: a real figure through the image-input path under ZDR.
    before = _meter_state(meter)
    if sample is None:
        checks.append(
            PreflightCheck(
                "vision", "warn", "no figure found in the selected documents; not exercised"
            )
        )
    else:
        f = sample.figure
        label = f"{sample.doc_key} figure {f.number or '(unnumbered)'} ({f.width}x{f.height}px)"
        try:
            result = OpenRouterFigureDescriber(client, vision_model).describe(f.png, f.caption, "")
            checks.append(
                PreflightCheck(
                    "vision",
                    "pass",
                    f"{label}: parsed; informational={result.informational}, "
                    f"{len(result.description)} chars",
                )
            )
        except BudgetExceededError:
            raise
        except Exception as exc:  # noqa: BLE001
            checks.append(PreflightCheck("vision", "fail", f"{label}: {type(exc).__name__}: {exc}"))
    vision_cost = _cost_source(meter, before)

    # (d) where each endpoint's price came from. Only chat asks for `usage.cost`; if the others
    # are not "reported" the meter is estimating, which is fine but worth knowing.
    checks.append(
        PreflightCheck(
            "cost reporting",
            "info",
            f"embeddings: {embed_cost}; rerank: {rerank_cost}; vision: {vision_cost} "
            "(reported = OpenRouter's usage.cost; estimated = tokens x our price table; "
            "unpriced = flat pessimistic fallback)",
        )
    )
    return PreflightReport(now().isoformat(timespec="seconds"), checks, meter.summary())


# Real ingest ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class DocResult:
    doc_key: str
    split: str
    # ingested | replaced | skipped-existing | stale | failed | not-reached
    status: str
    seconds: float = 0.0
    figures_total: int = 0
    figures_described: int = 0  # the vision call succeeded (informational or not)
    figures_degraded: int = 0  # the vision call failed: the chunk keeps its caption only
    failures: list[str] = field(default_factory=list)  # "item_ref: error"
    error: str = ""


@dataclass(frozen=True)
class IngestReport:
    mode: ClassVar[str] = "ingest"
    generated_at: str
    results: list[DocResult]
    meter_summary: str
    budget_exceeded: bool = False

    def markdown(self) -> str:
        done = [r for r in self.results if r.status in ("ingested", "replaced")]
        rows = [
            (
                r.doc_key,
                r.split,
                r.status,
                r.figures_total,
                r.figures_described,
                r.figures_degraded,
                r.seconds,
                r.error,
            )
            for r in self.results
        ]
        out = [
            "# Ingest run",
            "",
            f"Generated {self.generated_at}. "
            f"{len(done)} document(s) written, "
            f"{sum(1 for r in self.results if r.status == 'skipped-existing')} skipped "
            "(already there), "
            f"{sum(1 for r in self.results if r.status == 'not-reached')} not reached.",
            "",
        ]
        if self.budget_exceeded:
            out += [
                "**STOPPED: the spending cap was reached.** Re-run to continue; finished "
                "documents are skipped.",
                "",
            ]
        out += [
            _table(
                ["doc", "split", "status", "figures", "described", "degraded", "s", "error"], rows
            ),
            "",
            f"Spend: {self.meter_summary}",
            "",
            "## Ingest failures",
            "",
        ]
        failures = [(r.doc_key, f) for r in self.results for f in r.failures]
        out += [f"- `{k}` {f}" for k, f in failures] or ["None."]
        out.append("")
        return "\n".join(out)


class CountingDescriber:
    """Wraps a FigureDescriber to count successes/failures and show progress.

    Lets us report described-vs-degraded per document and print "still alive" lines without
    touching `ingest_document`. Failures are re-raised unchanged: ingest decides how to degrade
    (and BudgetExceededError must keep propagating, exactly as ingest itself ensures).
    """

    def __init__(self, inner: FigureDescriber, *, log: Log, every: int = 25) -> None:
        self._inner = inner
        self._log = log
        self._every = every
        self.described = 0
        self.failed = 0

    def describe(self, png: bytes, caption: str, context: str) -> Any:
        try:
            result = self._inner.describe(png, caption, context)
        except BudgetExceededError:
            raise
        except Exception:
            self.failed += 1
            raise
        else:
            self.described += 1
            return result
        finally:
            n = self.described + self.failed
            if n and n % self._every == 0:
                self._log(f"    {n} figures done ({self.failed} failed)")


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fetch_failures(conn: Conn, document_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT item_ref, error FROM ingest_failures WHERE document_id = %s ORDER BY id",
        (document_id,),
    ).fetchall()
    return [f"{ref}: {err}" for ref, err in rows]


def ingest_entry(
    conn: Conn,
    entry: ManifestEntry,
    data_dir: Path,
    *,
    embedder: Embedder,
    describer: FigureDescriber,
    parsers: Mapping[str, Parser] | None,
    replace: bool,
    log: Log,
    timer: Callable[[], float],
) -> DocResult:
    """Ingest one manifest entry in its own transaction. BudgetExceededError propagates (after
    the transaction rolled back)."""
    path = data_dir / entry.path
    start = timer()
    stored_sha = get_document_sha(conn, entry.doc_key)
    file_sha = _file_sha(path)
    # Check by doc_key BEFORE describing anything. `documents.doc_key` is UNIQUE, so a file whose
    # bytes changed but whose key exists would otherwise pay for every vision call and then die
    # on the unique constraint at insert time.
    if stored_sha is not None and not replace:
        status = "skipped-existing" if stored_sha == file_sha else "stale"
        error = (
            ""
            if status == "skipped-existing"
            else "source changed since ingest; rerun with --replace"
        )
        return DocResult(entry.doc_key, entry.split, status, round(timer() - start, 1), error=error)

    counter = CountingDescriber(describer, log=log)
    # Why ONE transaction per document: the document's rows, chunks, figures and embeddings
    # become visible together or not at all, so a crash, a Ctrl-C or an exhausted budget leaves
    # only whole documents (and a re-run simply continues). `conn.transaction()` commits on
    # exit; on an exception it rolls back and re-raises.
    with conn.transaction():
        replaced = replace and delete_document(conn, entry.doc_key)
        document_id = ingest_document(
            conn,
            parser_for(path, parsers),
            path,
            entry.to_source_info(),
            embedder=embedder,
            describer=counter,
        )
        if document_id is None:  # same bytes already ingested under another key
            if replace:  # raising rolls back the delete too, so nothing is lost
                raise RuntimeError("same source bytes are already ingested under another doc_key")
            return DocResult(
                entry.doc_key, entry.split, "skipped-existing", round(timer() - start, 1)
            )
        failures = _fetch_failures(conn, document_id)
        figures = conn.execute(
            "SELECT count(*) FROM chunks WHERE document_id = %s AND kind = 'figure'", (document_id,)
        ).fetchone()
    return DocResult(
        doc_key=entry.doc_key,
        split=entry.split,
        status="replaced" if replaced else "ingested",
        seconds=round(timer() - start, 1),
        figures_total=int(figures[0]) if figures else 0,
        figures_described=counter.described,
        figures_degraded=counter.failed,
        failures=[scrub(f, data_dir) for f in failures],
    )


def run_ingest(
    conn: Conn,
    entries: Sequence[ManifestEntry],
    data_dir: Path,
    *,
    embedder: Embedder,
    describer: FigureDescriber,
    meter: CostMeter,
    parsers: Mapping[str, Parser] | None = None,
    replace: bool = False,
    log: Log = print,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    timer: Callable[[], float] = time.monotonic,
) -> IngestReport:
    """Ingest the entries in order, one committed transaction each."""
    results: list[DocResult] = []
    exceeded = False
    for n, entry in enumerate(entries, 1):
        log(f"[{n}/{len(entries)}] {entry.doc_key} ...")
        try:
            result = ingest_entry(
                conn, entry, data_dir, embedder=embedder, describer=describer,
                parsers=parsers, replace=replace, log=log, timer=timer,
            )  # fmt: skip
        except BudgetExceededError as exc:
            log(f"    STOP: {exc}")
            results.append(DocResult(entry.doc_key, entry.split, "failed", error=f"budget: {exc}"))
            results += [DocResult(e.doc_key, e.split, "not-reached") for e in entries[n:]]
            exceeded = True
            break
        except Exception as exc:  # noqa: BLE001 - one bad document must not sink the others
            result = DocResult(
                entry.doc_key, entry.split, "failed",
                error=scrub(f"{type(exc).__name__}: {exc}", data_dir),
            )  # fmt: skip
        detail = f" in {result.seconds}s"
        if result.figures_total:
            detail += f" ({result.figures_described} figures described"
            detail += f", {result.figures_degraded} degraded)"
        log(f"    {result.status}{detail}" + (f": {result.error}" if result.error else ""))
        results.append(result)
    return IngestReport(now().isoformat(timespec="seconds"), results, meter.summary(), exceeded)


# Retry failures ------------------------------------------------------------------------------

_ITEM_REF = re.compile(r"^(?P<doc>.+)#chunk(?P<ordinal>\d+)$")


@dataclass(frozen=True)
class RetryResult:
    item_ref: str
    status: str  # resolved | still-failing | orphaned
    detail: str = ""


@dataclass(frozen=True)
class RetryReport:
    mode: ClassVar[str] = "retry-failures"
    generated_at: str
    results: list[RetryResult]
    meter_summary: str
    budget_exceeded: bool = False

    def markdown(self) -> str:
        out = ["# Retry of failed figure descriptions", "", f"Generated {self.generated_at}.", ""]
        if self.budget_exceeded:
            out += ["**STOPPED: the spending cap was reached.**", ""]
        out += [
            _table(
                ["item", "status", "detail"],
                [(r.item_ref, r.status, r.detail) for r in self.results],
            )
            if self.results
            else "No unresolved describe failures.",
            "",
            f"Spend: {self.meter_summary}",
            "",
        ]
        return "\n".join(out)


def retry_failures(
    conn: Conn,
    *,
    embedder: Embedder,
    describer: FigureDescriber,
    meter: CostMeter,
    log: Log = print,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> RetryReport:
    """Re-describe figures whose describe step failed; one transaction per figure.

    The chunk's stored content IS its caption-only text, so the new content is the description
    prepended to it (as `ingest_document` builds it). The text changed, so ALL of the chunk's
    embeddings are dropped (they describe the old text) and the configured model's is
    recomputed; other models' vectors can be rebuilt with `embed_missing`.
    """
    pending = conn.execute(
        "SELECT id, document_id, item_ref FROM ingest_failures"
        " WHERE stage = 'describe' AND resolved_at IS NULL ORDER BY id"
    ).fetchall()
    results: list[RetryResult] = []
    exceeded = False
    for failure_id, document_id, item_ref in pending:
        ref = str(item_ref)
        match = _ITEM_REF.match(ref)
        if document_id is None or match is None:
            # After --replace the old failure rows lose their document (ON DELETE SET NULL)
            # and point at chunks that no longer exist. Leave them, but say so.
            results.append(RetryResult(ref, "orphaned", "its document was deleted or replaced"))
            continue
        row = conn.execute(
            "SELECT c.id, c.content, coalesce(c.context_header, ''), f.png FROM chunks c"
            " JOIN figures f ON f.chunk_id = c.id"
            " WHERE c.document_id = %s AND c.ordinal = %s",
            (document_id, int(match["ordinal"])),
        ).fetchone()
        if row is None:
            results.append(RetryResult(ref, "orphaned", "no such figure chunk"))
            continue
        chunk_id, content, header, png = int(row[0]), str(row[1]), str(row[2]), bytes(row[3])
        try:
            with conn.transaction():
                result = describer.describe(png, content, header)
                if result.informational:
                    content = f"{result.description}\n\n{content}"
                conn.execute(
                    "UPDATE chunks SET content = %s, informational = %s WHERE id = %s",
                    (content, result.informational, chunk_id),
                )
                conn.execute("DELETE FROM embeddings WHERE chunk_id = %s", (chunk_id,))
                vectors = embedder.embed_documents([embed_text(header, content)])
                insert_embeddings(conn, embedder.model_key, [chunk_id], vectors)
                conn.execute(
                    "UPDATE ingest_failures SET resolved_at = now() WHERE id = %s", (failure_id,)
                )
        except BudgetExceededError as exc:
            log(f"STOP: {exc}")
            exceeded = True
            results.append(RetryResult(ref, "still-failing", f"budget: {exc}"))
            break
        except Exception as exc:  # noqa: BLE001 - leave the row unresolved for another try
            results.append(RetryResult(ref, "still-failing", f"{type(exc).__name__}: {exc}"[:300]))
            log(f"{ref}: still failing")
            continue
        results.append(RetryResult(ref, "resolved"))
        log(f"{ref}: resolved")
    return RetryReport(now().isoformat(timespec="seconds"), results, meter.summary(), exceeded)
