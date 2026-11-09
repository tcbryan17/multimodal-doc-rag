"""Ingest the fetched corpus into Postgres (build-plan step 14). See corpus_ingest.py.

Typical order, once the OpenRouter key is in .env:
  uv run python scripts/ingest_corpus.py --dry-run          # no key needed: sizes and costs
  uv run python scripts/ingest_corpus.py --preflight-only   # a few cents: verify live behaviour
  uv run python scripts/ingest_corpus.py                    # preflight, then the real ingest
  uv run python scripts/ingest_corpus.py --retry-failures   # re-describe degraded figures
Reports land in reports/ingest/.
"""

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from pgvector.psycopg import register_vector

from multimodal_doc_rag.config import settings
from multimodal_doc_rag.corpus_ingest import (
    DocStats,
    DryRunReport,
    Report,
    analyze_document,
    default_parsers,
    estimate_cost,
    parser_for,
    retry_failures,
    run_ingest,
    run_preflight,
    select_entries,
    smallest_figure,
    write_report,
)
from multimodal_doc_rag.db.migrate import migrate
from multimodal_doc_rag.fetch import load_manifest
from multimodal_doc_rag.models.adapters import OpenRouterEmbedder, OpenRouterFigureDescriber
from multimodal_doc_rag.models.cost import BudgetExceededError, CostMeter, Price
from multimodal_doc_rag.models.openrouter import OpenRouterClient

REPORT_DIR = Path("reports/ingest")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="parse + chunk + cost estimate only")
    mode.add_argument("--preflight-only", action="store_true", help="run just the canary")
    mode.add_argument(
        "--retry-failures", action="store_true", help="re-describe figures that failed to describe"
    )
    p.add_argument("--only", nargs="+", metavar="KEY", help="only these doc_keys")
    p.add_argument("--corpus", choices=["10k", "faa"], help="only this corpus")
    p.add_argument(
        "--replace", action="store_true", help="delete and re-ingest documents that already exist"
    )
    p.add_argument("--skip-preflight", action="store_true", help="skip the canary before ingest")
    p.add_argument("--budget", type=float, help="spending cap in USD (default INGEST_BUDGET_USD)")
    return p


def _meter(budget: float | None) -> CostMeter:
    return CostMeter(
        cap_usd=budget if budget is not None else settings.ingest_budget_usd,
        prices={m: Price(*p) for m, p in settings.model_prices.items()},
        unpriced_call_usd=settings.unpriced_call_usd,
    )


def _connect() -> psycopg.Connection[Any]:
    # autocommit=True means NO transaction is open between our explicit `conn.transaction()`
    # blocks, so each block is a real transaction that commits on exit (inside an already-open
    # transaction it would only be a savepoint and nothing would ever be committed).
    conn = psycopg.connect(settings.database_url.get_secret_value(), autocommit=True)
    print(f"migrations applied: {migrate(conn) or 'none (up to date)'}")
    register_vector(conn)  # after migrate: the `vector` type must exist first
    return conn


def _save(report: Report, now: datetime) -> None:
    md, js = write_report(report, REPORT_DIR, now)
    print(f"report: {md}\n        {js}")


def dry_run(args: argparse.Namespace) -> int:
    entries = select_entries(load_manifest(settings.data_dir), only=args.only, corpus=args.corpus)
    parsers = default_parsers()
    stats: list[DocStats] = []
    failed: dict[str, str] = {}
    for n, entry in enumerate(entries, 1):
        path = settings.data_dir / entry.path
        print(f"[{n}/{len(entries)}] parsing {entry.doc_key} ...", flush=True)
        t0 = time.monotonic()
        try:
            parsed = parser_for(path, parsers).parse(path, entry.to_source_info())
        except Exception as exc:  # noqa: BLE001 - report it, keep going
            failed[entry.doc_key] = f"{type(exc).__name__}: {exc}"[:300]
            continue
        stats.append(analyze_document(entry, parsed, seconds=time.monotonic() - t0))
    now = datetime.now(UTC)
    estimate = estimate_cost(
        stats,
        embedding_model=settings.embedding_model,
        vision_model=settings.vision_model,
        prices={m: Price(*p) for m, p in settings.model_prices.items()},
    )
    report = DryRunReport(now.isoformat(timespec="seconds"), stats, estimate, failed)
    _save(report, now)
    print(f"estimated cost: ${estimate.total_usd} (suggested credit limit "
          f"${estimate.suggested_credit_limit_usd:.2f})")  # fmt: skip
    return 1 if failed else 0


def main() -> int:
    args = build_parser().parse_args()
    if args.dry_run:
        return dry_run(args)

    if settings.openrouter_api_key is None:
        print("OPENROUTER_API_KEY is not set; add it to .env (or use --dry-run).", file=sys.stderr)
        return 2
    meter = _meter(args.budget)
    client = OpenRouterClient.from_settings(meter=meter)
    embedder = OpenRouterEmbedder.from_settings(settings, client)
    describer = OpenRouterFigureDescriber.from_settings(settings, client)
    try:
        if args.retry_failures:
            conn = _connect()
            retried = retry_failures(conn, embedder=embedder, describer=describer, meter=meter)
            _save(retried, datetime.now(UTC))
            return 0

        entries = select_entries(
            load_manifest(settings.data_dir), only=args.only, corpus=args.corpus
        )
        if not entries:
            print("no documents selected (is data/manifest.json present?)", file=sys.stderr)
            return 2
        if not args.skip_preflight:
            # Needs no database: a failed canary never touches it.
            print("preflight: finding a figure to test with ...", flush=True)
            sample = smallest_figure(entries, settings.data_dir, default_parsers())
            pre = run_preflight(
                client,
                embedding_model=settings.embedding_model,
                embedding_dim=settings.embedding_dim,
                rerank_model=settings.rerank_model,
                vision_model=settings.vision_model,
                vision_reasoning=settings.vision_reasoning,
                sample=sample,
            )
            _save(pre, datetime.now(UTC))
            print(pre.markdown())
            if not pre.ok:
                print("Preflight FAILED: not ingesting.", file=sys.stderr)
                return 1
        if args.preflight_only:
            return 0

        conn = _connect()
        report = run_ingest(
            conn,
            entries,
            settings.data_dir,
            embedder=embedder,
            describer=describer,
            meter=meter,
            parsers=default_parsers(),
            replace=args.replace,
        )
        _save(report, datetime.now(UTC))
        print(report.meter_summary)
        bad = any(r.status in ("failed", "stale") for r in report.results)
        return 1 if bad or report.budget_exceeded else 0
    except BudgetExceededError as exc:  # during preflight
        print(f"STOPPED: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
