"""Create the eval-only database `rag_eval` and plant the poisoned document in it (ADR 0011).

  uv run python scripts/make_eval_index.py [--recreate]

Copies the already-ingested `rag` (free, no model calls), then ingests a synthetic poisoned
handbook chapter into the copy only, using the real embedder and describer (a few cents,
capped by --budget). Stop the API server and close other sessions on `rag` first: Postgres
refuses to copy a database that anyone else is connected to.

Then:  uv run python scripts/run_eval.py --injection --database-url <printed url> ...
"""

import argparse
import importlib.util
import sys
import tempfile
from pathlib import Path
from typing import Any

import psycopg

from multimodal_doc_rag.config import settings
from multimodal_doc_rag.evals.index import (
    EVAL_DB_NAME,
    EvalIndexError,
    create_eval_database,
    db_name,
    ingest_poisoned,
    with_db,
)
from multimodal_doc_rag.evals.wiring import build_meter
from multimodal_doc_rag.models.adapters import OpenRouterEmbedder, OpenRouterFigureDescriber
from multimodal_doc_rag.models.openrouter import OpenRouterClient

ROOT = Path(__file__).resolve().parent.parent


def _load_generator() -> Any:
    path = ROOT / "evals" / "poisoned" / "make_poisoned_handbook.py"
    spec = importlib.util.spec_from_file_location("make_poisoned_handbook", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--recreate", action="store_true", help="drop and re-copy an existing rag_eval")
    p.add_argument("--budget", type=float, default=settings.ingest_budget_usd, help="USD cap")
    a = p.parse_args()

    source_url = settings.database_url.get_secret_value()
    source = db_name(source_url)
    try:
        create_eval_database(source_url, source, EVAL_DB_NAME, a.recreate)
    except EvalIndexError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"copied {source!r} -> {EVAL_DB_NAME!r}")

    eval_url = with_db(source_url, EVAL_DB_NAME)
    meter = build_meter(settings, a.budget)
    client = OpenRouterClient.from_settings(meter=meter)
    try:
        with tempfile.TemporaryDirectory() as tmp, psycopg.connect(eval_url) as conn:
            pdf = Path(tmp) / "poisoned.pdf"
            _load_generator().build(pdf)
            doc_id = ingest_poisoned(
                conn,
                pdf,
                embedder=OpenRouterEmbedder.from_settings(settings, client),
                describer=OpenRouterFigureDescriber(client, settings.vision_model),
            )
            conn.commit()  # one document, one atomic commit (never touches the real index)
    finally:
        client.close()
    print(f"poisoned document id {doc_id}; {meter.summary()}")
    print("next: uv run python scripts/run_eval.py --injection --eval-index --label injection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
