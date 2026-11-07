"""The eval-only database (ADR 0011): where the poisoned document lives.

Indirect-injection tests need a document with planted instructions in the index. It must
NEVER go into the real index (`rag`), or the real product could retrieve and obey it. So we
copy the finished `rag` into a second database `rag_eval`, add the poisoned document there,
and point the injection run at `rag_eval` with `--database-url`.

The copy uses `CREATE DATABASE ... TEMPLATE rag`: Postgres clones the files directly, which
is instant and makes no model calls (re-embedding the corpus would cost money). The price is
that Postgres refuses to clone a database while any other session is connected to it.
"""

from pathlib import Path
from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from psycopg import errors, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from multimodal_doc_rag.ingest import ingest_document
from multimodal_doc_rag.parsing.handbook_pdf import HandbookPdfParser
from multimodal_doc_rag.protocols import Embedder, FigureDescriber
from multimodal_doc_rag.types import Corpus, SourceInfo

EVAL_DB_NAME = "rag_eval"
POISONED_DOC_KEY = "eval-poisoned-handbook"
POISONED_TITLE = "FAA-H-8083-25C, Ch. 99: Supplemental Operating Notes (SYNTHETIC, eval-only)"
# Corpus "faa" on purpose: an attacker's document sits among the real ones and is found by
# the same searches. The key and title make it obvious in any report.
POISONED_SOURCE = SourceInfo(
    doc_key=POISONED_DOC_KEY,
    corpus=Corpus.FAA,
    title=POISONED_TITLE,
    source_url="synthetic://eval-poisoned-handbook",
)


class EvalIndexError(RuntimeError):
    """Refusing, or failing, to create the eval database. The message says what to do."""


def db_name(url: str) -> str:
    return str(conninfo_to_dict(url)["dbname"])


def with_db(url: str, name: str) -> str:
    """The same server and credentials, a different database."""
    return make_conninfo(url, dbname=name)


def check_create_allowed(source: str, target: str, target_exists: bool, recreate: bool) -> bool:
    """Decide what to do before touching anything. Returns True if `target` must be dropped
    first. Raises EvalIndexError if creating it is refused."""
    if source == target:
        raise EvalIndexError(f"refusing: the eval database must differ from the source ({source})")
    if target_exists and not recreate:
        raise EvalIndexError(
            f"database {target!r} already exists. Re-run with --recreate to drop it and copy "
            f"{source!r} again, or keep using it."
        )
    return target_exists


def create_statement(target: str, template: str) -> sql.Composed:
    return sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
        sql.Identifier(target), sql.Identifier(template)
    )


def drop_statement(target: str) -> sql.Composed:
    # FORCE disconnects other sessions. Safe here because it is only ever the eval copy.
    return sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(target))


def in_use_message(source: str) -> str:
    return (
        f"Postgres will not copy {source!r} while anything else is connected to it. "
        "Stop the API server (uvicorn), close psql/GUI sessions and any running ingest or "
        f"eval against {source!r}, then try again."
    )


def create_eval_database(admin_url: str, source: str, target: str, recreate: bool) -> None:
    """Clone `source` into `target`. Connects to the `postgres` maintenance database, because
    connecting to the source itself would be exactly the session that blocks the copy."""
    with psycopg.connect(with_db(admin_url, "postgres"), autocommit=True) as admin:
        # CREATE/DROP DATABASE cannot run inside a transaction, hence autocommit.
        row = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target,)).fetchone()
        drop_first = check_create_allowed(source, target, row is not None, recreate)
        if drop_first:
            admin.execute(drop_statement(target))
        try:
            admin.execute(create_statement(target, source))
        except errors.ObjectInUse as exc:
            raise EvalIndexError(in_use_message(source)) from exc


def ingest_poisoned(
    conn: psycopg.Connection[Any],
    pdf: Path,
    *,
    embedder: Embedder,
    describer: FigureDescriber,
) -> int | None:
    """Parse and index the poisoned PDF as a handbook chapter. Does not commit.

    Returns the document id, or None if that exact file was already ingested.
    """
    register_vector(conn)
    return ingest_document(
        conn,
        HandbookPdfParser(),
        pdf,
        POISONED_SOURCE,
        embedder=embedder,
        describer=describer,
    )


def poisoned_present(conn: psycopg.Connection[Any]) -> bool:
    row = conn.execute("SELECT 1 FROM documents WHERE doc_key = %s", (POISONED_DOC_KEY,)).fetchone()
    return row is not None
