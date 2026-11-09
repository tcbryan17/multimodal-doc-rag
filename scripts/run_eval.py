"""Run the eval: ask every verified gold question, score it, write a report (ADR 0011).

  uv run python scripts/run_eval.py --corpus faa --limit 5 --no-judge --label smoke
  uv run python scripts/run_eval.py --label baseline
  uv run python scripts/run_eval.py --injection --eval-index --label injection

Makes real, paid model calls (capped by --budget). Reports land in evals/reports/.
"""

import argparse
import sys
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from multimodal_doc_rag.config import settings
from multimodal_doc_rag.evals.chunk_index import chunk_db_name
from multimodal_doc_rag.evals.gates import (
    load_gates,
    load_minimums,
    report_section,
    unembedded_chunks,
)
from multimodal_doc_rag.evals.gold import (
    GoldError,
    GoldItem,
    InjectionItem,
    check_splits,
    load_gold,
    load_injection,
)
from multimodal_doc_rag.evals.index import EVAL_DB_NAME, db_name, poisoned_present, with_db
from multimodal_doc_rag.evals.judge import JudgeConfigError
from multimodal_doc_rag.evals.report import render_json, render_markdown, report_paths
from multimodal_doc_rag.evals.results import RunConfig
from multimodal_doc_rag.evals.runner import (
    OptionsError,
    RunOptions,
    git_state,
    index_stats,
    run_eval,
    select_items,
    utc_stamp,
    validate_options,
)
from multimodal_doc_rag.evals.wiring import build_components, generator_warning
from multimodal_doc_rag.fetch import load_manifest

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
CANDIDATES = 30


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--corpus", choices=["10k", "faa"], help="default: both")
    p.add_argument("--split", choices=["dev", "heldout"], default="dev")
    p.add_argument("--i-know-this-is-heldout", action="store_true")
    p.add_argument("--limit", type=int, help="only the first N questions (by id)")
    p.add_argument(
        "--type",
        choices=["fact", "figure", "concept"],
        help="only this kind of question (a smoke test; such a run can't bind)",
    )
    p.add_argument("--generator", default=settings.generation_model)
    p.add_argument("--no-rerank", action="store_true")
    p.add_argument(
        "--reasoning",
        action=argparse.BooleanOptionalAction,
        default=settings.generation_reasoning,
        help="generator hidden reasoning on/off (ADR 0015; default GENERATION_REASONING)",
    )
    p.add_argument("--top-k", type=int, default=5, help="passages given to the generator")
    p.add_argument("--recall-k", type=int, default=5, help="k for recall@k (<= --top-k)")
    p.add_argument("--budget", type=float, default=settings.eval_budget_usd, help="USD cap")
    p.add_argument("--no-judge", action="store_true", help="retrieval + rule metrics only")
    p.add_argument(
        "--corpus-filter",
        action="store_true",
        help="restrict retrieval to each question's corpus (comparison; default searches all)",
    )
    p.add_argument(
        "--no-figure-images",
        action="store_true",
        help="withhold figure images from the generator: descriptions only (comparison)",
    )
    p.add_argument("--label", default="run", help="free text for the report file name")
    p.add_argument("--include-drafts", action="store_true", help="smoke test on unverified items")
    p.add_argument("--injection", action="store_true", help="also run the injection sets")
    p.add_argument("--database-url", help="default: DATABASE_URL")
    which = p.add_mutually_exclusive_group()
    which.add_argument(
        "--eval-index", action="store_true", help="use the eval-only database rag_eval"
    )
    which.add_argument(
        "--chunk-tokens",
        type=int,
        metavar="N",
        help="use the chunk-size comparison database rag_chunkN (scripts/make_chunk_index.py)",
    )
    a = p.parse_args()

    opts = RunOptions(
        corpus=a.corpus,
        split=a.split,
        i_know_this_is_heldout=a.i_know_this_is_heldout,
        limit=a.limit,
        top_k=a.top_k,
        recall_k=a.recall_k,
        budget_usd=a.budget,
        judge=not a.no_judge,
        include_drafts=a.include_drafts,
        rerank=not a.no_rerank,
        generator=a.generator,
        corpus_filter=a.corpus_filter,
        figure_images=not a.no_figure_images,
    )
    try:
        warnings = validate_options(opts)
    except OptionsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if (w := generator_warning(a.generator)) is not None:
        warnings.append(w)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)

    doc_splits = {e.doc_key: e.split for e in load_manifest(settings.data_dir)}
    if not doc_splits:
        print("error: no manifest; run scripts/fetch_corpus.py first", file=sys.stderr)
        return 2
    corpora = [a.corpus] if a.corpus else ["10k", "faa"]
    all_items: list[GoldItem] = []
    try:
        for c in corpora:
            all_items += load_gold(EVALS / "gold" / f"{c}.jsonl")
        items = select_items(
            all_items,
            corpus=a.corpus,
            split=a.split,
            include_drafts=a.include_drafts,
            limit=a.limit,
            question_type=a.type,
        )
        check_splits(items, doc_splits)
    except GoldError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    injection: list[InjectionItem] = []
    if a.injection:
        allowed = {"verified", "draft"} if a.include_drafts else {"verified"}
        for kind in ("direct", "indirect"):
            injection += [
                i
                for i in load_injection(EVALS / "injection" / f"{kind}.jsonl")
                if i.status in allowed
            ]
    if not items and not injection:
        print(
            "error: no verified questions to run. Draft and review some "
            "(scripts/draft_gold.py), or smoke-test with --include-drafts.",
            file=sys.stderr,
        )
        return 2

    url = a.database_url or settings.database_url.get_secret_value()
    if a.eval_index:
        url = with_db(url, EVAL_DB_NAME)
    if a.chunk_tokens is not None:
        url = with_db(url, chunk_db_name(a.chunk_tokens))
    with psycopg.connect(url) as conn:
        register_vector(conn)
        index = index_stats(conn, settings.embedding_key)
        if (gap := unembedded_chunks(index)) is not None:
            # Not a warning: the run would finish and report a recall that is quietly too low.
            print(
                f"error: {gap} in {db_name(url)!r}. Run scripts/embed_missing.py first "
                "(with the same EMBEDDING_MODEL and EMBEDDING_DIM).",
                file=sys.stderr,
            )
            return 2
        if any(i.kind == "indirect" for i in injection) and not poisoned_present(conn):
            print(
                f"warning: {db_name(url)!r} has no poisoned document, so the indirect "
                "questions are skipped. Run scripts/make_eval_index.py and pass "
                "--eval-index.",
                file=sys.stderr,
            )
            injection = [i for i in injection if i.kind != "indirect"]
        elif poisoned_present(conn):
            print(
                "warning: this index contains the poisoned document, which can also show up "
                "in ordinary FAA retrieval. Use this run for injection results only.",
                file=sys.stderr,
            )
        try:
            parts = build_components(
                settings,
                conn,
                generator_model=a.generator,
                rerank=not a.no_rerank,
                top_k=a.top_k,
                candidates=CANDIDATES,
                budget_usd=a.budget,
                use_judge=not a.no_judge,
                generator_reasoning=a.reasoning,
                figure_images=not a.no_figure_images,
            )
        except JudgeConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        commit, dirty = git_state(ROOT)
        started = utc_stamp()
        config = RunConfig(
            label=a.label,
            started_utc=started,
            git_commit=commit,
            git_dirty=dirty,
            corpus=a.corpus or "all",
            split=a.split,
            generator_model=a.generator,
            generator_reasoning=a.reasoning,
            corpus_filter=a.corpus_filter,
            figure_images=not a.no_figure_images,
            judge_model=settings.judge_model if not a.no_judge else None,
            embedding_model=settings.embedding_model,
            rerank_model=None if a.no_rerank else settings.rerank_model,
            top_k=a.top_k,
            recall_k=a.recall_k,
            candidates=CANDIDATES,
            budget_usd=a.budget,
            include_drafts=a.include_drafts,
            limit=a.limit,
            question_type=a.type,
            index=index,
            database=db_name(url),
        )
        try:
            report = run_eval(
                config,
                items,
                injection,
                parts.pipeline,
                parts.judge,
                parts.meter,
                progress=lambda m: print(m, file=sys.stderr),
            )
        finally:
            parts.client.close()
        conn.rollback()  # read-only run: nothing to keep

    json_path, md_path = report_paths(EVALS / "reports", started, a.label)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(render_json(report), encoding="utf-8")
    gates_file = EVALS / "gates.toml"
    gates_section = report_section(report, load_gates(gates_file), load_minimums(gates_file))
    md_path.write_text(render_markdown(report, gates_section), encoding="utf-8")
    print(f"wrote {md_path.relative_to(ROOT)} and {json_path.name}")
    print(report.meter_summary)
    if report.truncated:
        print(f"CUT SHORT: {report.truncated_reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
