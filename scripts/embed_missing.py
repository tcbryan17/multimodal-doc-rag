"""Embed every chunk that has no vector yet for the configured embedding model (ADR 0010).

This is how a second embedder is added for the embedder comparison (ADR 0011) without
re-ingesting: the chunks and figure descriptions stay, only new vectors are computed. The
model comes from the settings, so override it in the environment for one command:

  EMBEDDING_MODEL=openai/text-embedding-3-small EMBEDDING_DIM=1536 \\
      uv run python scripts/embed_missing.py --dry-run
  EMBEDDING_MODEL=openai/text-embedding-3-small EMBEDDING_DIM=1536 \\
      uv run python scripts/embed_missing.py
  EMBEDDING_MODEL=openai/text-embedding-3-small EMBEDDING_DIM=1536 \\
      uv run python scripts/run_eval.py --label embedder-openai-3-small

--dry-run makes no model calls. A real run is capped by --budget, commits batch by batch,
and can simply be re-run: chunks that already have a vector are skipped.
"""

import argparse
import sys

import psycopg
from pgvector.psycopg import register_vector

from multimodal_doc_rag.config import settings
from multimodal_doc_rag.db.repository import count_missing_embeddings, embed_missing
from multimodal_doc_rag.evals.index import db_name
from multimodal_doc_rag.evals.wiring import build_meter
from multimodal_doc_rag.models.adapters import OpenRouterEmbedder
from multimodal_doc_rag.models.cost import BudgetExceededError
from multimodal_doc_rag.models.openrouter import OpenRouterClient
from multimodal_doc_rag.search import has_vector_index


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="count and estimate only")
    p.add_argument("--budget", type=float, default=settings.eval_budget_usd, help="USD cap")
    p.add_argument("--database-url", help="default: DATABASE_URL")
    a = p.parse_args()

    key = settings.embedding_key
    url = a.database_url or settings.database_url.get_secret_value()
    # autocommit: each batch of vectors is saved as soon as it is written, so a run stopped
    # by the cap (or Ctrl-C) keeps what it paid for and a re-run continues from there.
    with psycopg.connect(url, autocommit=True) as conn:
        register_vector(conn)
        chunks, tokens = count_missing_embeddings(conn, key)
        price = settings.model_prices.get(settings.embedding_model)
        cost = f"about ${tokens * price[0] / 1e6:.4f}" if price else "no price in MODEL_PRICES"
        print(
            f"{db_name(url)!r}: {chunks} chunks have no {key} vector (~{tokens:,} tokens, {cost})"
        )
        if not has_vector_index(conn, key):
            print(
                f"note: no HNSW index for {key}. Search will scan every vector, which is fine "
                "for a comparison run; a model that serves /ask needs its own index (a new "
                "migration, see migrations/0001_init.sql).",
                file=sys.stderr,
            )
        if a.dry_run or chunks == 0:
            return 0
        if settings.openrouter_api_key is None:
            print("error: OPENROUTER_API_KEY is not set; add it to .env", file=sys.stderr)
            return 2

        meter = build_meter(settings, a.budget)
        client = OpenRouterClient.from_settings(meter=meter)
        try:
            done = embed_missing(conn, OpenRouterEmbedder.from_settings(settings, client))
        except BudgetExceededError as exc:
            print(f"STOPPED: {exc}. Re-run to continue.", file=sys.stderr)
            return 1
        finally:
            client.close()
            print(meter.summary())
    print(f"embedded {done} chunks with {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
