"""Draft, review and hand-add gold questions (ADR 0011).

  uv run python scripts/draft_gold.py draft --corpus faa --split dev --n 20
  uv run python scripts/draft_gold.py review --corpus faa
  uv run python scripts/draft_gold.py add --corpus faa --type figure        (you write it)
  uv run python scripts/draft_gold.py review-injection --kind direct

`draft` calls a model (capped by --budget) and appends status=draft items to
evals/gold/<corpus>.jsonl. Nothing counts in an eval until you verify it.
"""

import argparse
import sys
from pathlib import Path
from typing import Any, cast

import psycopg

from multimodal_doc_rag.config import settings
from multimodal_doc_rag.evals.draft import (
    draft_items,
    draftable_doc_keys,
    exclude_used,
    fetch_candidate_chunks,
    merge_drafts,
    plan_counts,
    sample_sources,
    split_sources,
)
from multimodal_doc_rag.evals.gold import (
    CorpusName,
    GoldError,
    QuestionType,
    SplitName,
    check_splits,
    load_gold,
    load_injection,
    save_gold,
    save_injection,
)
from multimodal_doc_rag.evals.review import owner_item, review_injection, review_loop
from multimodal_doc_rag.evals.wiring import build_meter
from multimodal_doc_rag.fetch import load_manifest
from multimodal_doc_rag.models.openrouter import OpenRouterClient

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "evals" / "gold"


def _doc_splits() -> dict[str, str]:
    splits = {e.doc_key: e.split for e in load_manifest(settings.data_dir)}
    if not splits:
        raise SystemExit("error: no manifest; run scripts/fetch_corpus.py first")
    return splits


def cmd_draft(a: argparse.Namespace) -> int:
    corpus = cast(CorpusName, a.corpus)
    split = cast(SplitName, a.split)
    path = GOLD / f"{corpus}.jsonl"
    existing = load_gold(path)
    doc_splits = _doc_splits()
    manifest = load_manifest(settings.data_dir)
    all_keys = [e.doc_key for e in manifest if e.corpus.value == corpus and e.split == split]
    skip = None if a.skip_docs is None else [k.strip() for k in a.skip_docs.split(",") if k]
    try:
        keys = draftable_doc_keys(all_keys, skip)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if skipped := sorted(set(all_keys) - set(keys)):
        print(f"not drafting from: {', '.join(skipped)} (still searched; see --skip-docs)")
    n_ans, n_unans = plan_counts(a.n)
    with psycopg.connect(settings.database_url.get_secret_value()) as conn:
        by_doc = exclude_used(fetch_candidate_chunks(conn, keys), existing)
    if not any(by_doc.values()):
        print(f"error: no ingested {corpus}/{split} chunks to draft from", file=sys.stderr)
        return 2
    picked = sample_sources(by_doc, n_ans + n_unans, a.seed)
    answerable, unanswerable = split_sources(picked, n_unans, a.seed)
    meter = build_meter(settings, a.budget)
    client = OpenRouterClient.from_settings(meter=meter)
    try:
        outcome = draft_items(
            client,
            a.model or settings.generation_model,
            corpus=corpus,
            split=split,
            answerable_sources=answerable,
            unanswerable_sources=unanswerable,
            existing=existing,
        )
    finally:
        client.close()
    check_splits(outcome.items, doc_splits)
    save_gold(path, merge_drafts(existing, outcome.items))
    for err in outcome.errors:
        print(f"skipped: {err}", file=sys.stderr)
    if outcome.stopped_by_budget:
        print("stopped early: spending cap reached", file=sys.stderr)
    print(f"added {len(outcome.items)} drafts to {path.relative_to(ROOT)}; {meter.summary()}")
    print(f"next: uv run python scripts/draft_gold.py review --corpus {corpus}")
    return 0


def cmd_review(a: argparse.Namespace) -> int:
    path = GOLD / f"{a.corpus}.jsonl"
    items = load_gold(path)
    counts = review_loop(items, input, print, lambda cur: save_gold(path, cur), _doc_splits())
    print(f"done: {dict(counts)}")
    return 0


def cmd_add(a: argparse.Namespace) -> int:
    path = GOLD / f"{a.corpus}.jsonl"
    items = load_gold(path)
    from multimodal_doc_rag.evals.draft import next_ids

    new_id = next_ids(items, a.corpus, a.split, 1)[0]
    print(f"new item {new_id} (a {a.type} question; blank reference + pages = unanswerable)")
    question = input("question > ").strip()
    reference = input("reference answer > ").strip() or None
    pages = input("gold pages doc:idx[:label], ... > ").strip() if reference else ""
    try:
        item = owner_item(
            id=new_id,
            corpus=cast(CorpusName, a.corpus),
            split=cast(SplitName, a.split),
            type=cast(QuestionType, a.type),
            question=question,
            reference_answer=reference,
            pages=pages,
        )
        check_splits([item], _doc_splits())
    except (ValueError, GoldError) as exc:
        print(f"not saved: {exc}", file=sys.stderr)
        return 2
    save_gold(path, merge_drafts(items, [item]))
    print(f"saved {new_id} as verified (origin: owner)")
    return 0


def cmd_review_injection(a: argparse.Namespace) -> int:
    path = ROOT / "evals" / "injection" / f"{a.kind}.jsonl"
    items = load_injection(path)
    counts = review_injection(items, input, print, lambda cur: save_injection(path, cur))
    print(f"done: {dict(counts)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft", help="model drafts questions from ingested chunks")
    d.add_argument("--corpus", required=True, choices=["10k", "faa"])
    d.add_argument("--split", default="dev", choices=["dev", "heldout"])
    d.add_argument("--n", type=int, default=20, help="drafts to write (~10%% unanswerable)")
    d.add_argument("--seed", type=int, default=0)
    d.add_argument("--model", help="default: GENERATION_MODEL")
    d.add_argument(
        "--skip-docs",
        help="comma-separated doc keys never used as sources (default: phak-index,phak-front "
        "where present; pass '' to skip none)",
    )
    d.add_argument("--budget", type=float, default=settings.eval_budget_usd)
    r = sub.add_parser("review", help="verify / edit / reject drafts one at a time")
    r.add_argument("--corpus", required=True, choices=["10k", "faa"])
    add = sub.add_parser("add", help="write one question yourself (e.g. a figure question)")
    add.add_argument("--corpus", required=True, choices=["10k", "faa"])
    add.add_argument("--split", default="dev", choices=["dev", "heldout"])
    add.add_argument("--type", default="figure", choices=["fact", "figure", "concept"])
    ri = sub.add_parser("review-injection", help="verify or reject the injection questions")
    ri.add_argument("--kind", required=True, choices=["direct", "indirect"])
    a = p.parse_args()
    handlers: dict[str, Any] = {
        "draft": cmd_draft,
        "review": cmd_review,
        "add": cmd_add,
        "review-injection": cmd_review_injection,
    }
    return int(handlers[a.cmd](a))


if __name__ == "__main__":
    raise SystemExit(main())
