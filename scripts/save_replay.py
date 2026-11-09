"""Run one real question and save the response as replay/sample-run.json (build-plan step 16).

  uv run python scripts/save_replay.py --question "What does a turn coordinator show?" [--force]

Costs a few cents of OpenRouter credit (capped at $0.10). Figures are inlined as data URIs so
the static portfolio site can show them without a backend.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from multimodal_doc_rag.api import build_pipeline
from multimodal_doc_rag.config import settings
from multimodal_doc_rag.contracts import AskRequest
from multimodal_doc_rag.models.cost import CostMeter, Price
from multimodal_doc_rag.models.openrouter import OpenRouterClient
from multimodal_doc_rag.replay import figure_chunk_ids, inline_figures
from multimodal_doc_rag.search import fetch_figure_pngs

REPLAY_PATH = Path("replay/sample-run.json")
# The /ask response has no room for the question (the contract is fixed), so it goes beside it.
META_PATH = Path("replay/sample-run.meta.json")
CAP_USD = 0.10


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--question", required=True)
    p.add_argument("--corpus", choices=["10k", "faa"])
    p.add_argument("--doc", help="restrict to one doc_key")
    p.add_argument("--force", action="store_true", help="overwrite an existing replay file")
    args = p.parse_args()

    # Refuse before building a client or spending anything.
    if REPLAY_PATH.exists() and not args.force:
        print(f"{REPLAY_PATH} exists; pass --force to overwrite it.", file=sys.stderr)
        return 1
    if settings.openrouter_api_key is None:
        print("OPENROUTER_API_KEY is not set; add it to .env", file=sys.stderr)
        return 2

    meter = CostMeter(
        CAP_USD,
        prices={m: Price(*v) for m, v in settings.model_prices.items()},
        unpriced_call_usd=settings.unpriced_call_usd,
    )
    client = OpenRouterClient.from_settings(meter=meter)
    try:
        with psycopg.connect(settings.database_url.get_secret_value()) as conn:
            register_vector(conn)
            response = build_pipeline(conn, client).ask(
                AskRequest(question=args.question, corpus=args.corpus, doc=args.doc)
            )
            pngs = fetch_figure_pngs(conn, figure_chunk_ids(response))
    finally:
        client.close()

    response = inline_figures(response, pngs)
    REPLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
    # exclude_none matches the API's response_model_exclude_none=True output.
    REPLAY_PATH.write_text(response.model_dump_json(indent=2, exclude_none=True) + "\n")
    meta = {
        "question": args.question,
        "corpus": args.corpus,
        "doc": args.doc,
        "recorded_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "generation_model": settings.generation_model,
        "generation_reasoning": settings.generation_reasoning,
        "cost_usd": round(meter.spent_usd, 6),
    }
    META_PATH.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"saved {REPLAY_PATH} ({len(response.citations)} citations); {meter.summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
