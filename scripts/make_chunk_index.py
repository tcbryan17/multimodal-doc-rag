"""Build a comparison index at another chunk size, in its own database (ADR 0011, 0017).

  uv run python scripts/make_chunk_index.py --max-tokens 256
  uv run python scripts/make_chunk_index.py --max-tokens 1024
  uv run python scripts/run_eval.py --chunk-tokens 256 --label chunk-256

Re-parses and re-chunks the corpus into `rag_chunk<N>` and embeds it (embedding calls only,
capped by --budget). Figure descriptions are copied from the already-ingested index, so no
vision call is repeated. The real index (`rag`) is only read. Parsing the handbook takes a
few minutes. A stopped run can be re-run: finished documents are skipped.
"""

import argparse
import sys

import psycopg
from pgvector.psycopg import register_vector

from multimodal_doc_rag.config import settings
from multimodal_doc_rag.corpus_ingest import default_parsers, select_entries
from multimodal_doc_rag.db.migrate import migrate
from multimodal_doc_rag.evals.chunk_index import (
    ChunkIndexError,
    build_chunk_index,
    chunk_db_name,
    create_chunk_database,
    load_stored_figures,
)
from multimodal_doc_rag.evals.index import db_name, with_db
from multimodal_doc_rag.evals.wiring import build_meter
from multimodal_doc_rag.fetch import load_manifest
from multimodal_doc_rag.models.adapters import OpenRouterEmbedder
from multimodal_doc_rag.models.cost import BudgetExceededError
from multimodal_doc_rag.models.openrouter import OpenRouterClient


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--max-tokens", type=int, required=True, help="chunk size, e.g. 256 or 1024")
    p.add_argument("--recreate", action="store_true", help="drop the database and start again")
    p.add_argument("--budget", type=float, default=settings.ingest_budget_usd, help="USD cap")
    a = p.parse_args()
    if a.max_tokens < 1:
        p.error("--max-tokens must be at least 1")
    if settings.openrouter_api_key is None:
        print("error: OPENROUTER_API_KEY is not set; add it to .env", file=sys.stderr)
        return 2

    entries = select_entries(load_manifest(settings.data_dir))
    if not entries:
        print("error: no manifest; run scripts/fetch_corpus.py first", file=sys.stderr)
        return 2
    source_url = settings.database_url.get_secret_value()
    target = chunk_db_name(a.max_tokens)
    with psycopg.connect(source_url) as source:
        stored = load_stored_figures(source)
    created = create_chunk_database(source_url, target, a.recreate)
    print(f"{'created' if created else 'continuing'} {target!r} (source: {db_name(source_url)!r})")

    meter = build_meter(settings, a.budget)
    client = OpenRouterClient.from_settings(meter=meter)
    try:
        # autocommit so each document's `conn.transaction()` is a real, committed transaction.
        with psycopg.connect(with_db(source_url, target), autocommit=True) as conn:
            migrate(conn)
            register_vector(conn)  # after migrate: the `vector` type must exist first
            results = build_chunk_index(
                conn,
                entries,
                settings.data_dir,
                stored,
                max_tokens=a.max_tokens,
                embedder=OpenRouterEmbedder.from_settings(settings, client),
                parsers=default_parsers(),
            )
    except BudgetExceededError as exc:
        print(f"STOPPED: {exc}. Re-run to continue.", file=sys.stderr)
        return 1
    except ChunkIndexError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        client.close()
        print(meter.summary())
    indexed = [r for r in results if r.status == "indexed"]
    print(
        f"{len(indexed)} document(s) indexed ({sum(r.chunks for r in indexed)} chunks), "
        f"{len(results) - len(indexed)} already there"
    )
    print(
        f"next: uv run python scripts/run_eval.py --chunk-tokens {a.max_tokens} "
        f"--label chunk-{a.max_tokens}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
