"""HTTP API: `/health` and `/ask` (contract in README and ADR 0005)."""

import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from multimodal_doc_rag.config import settings
from multimodal_doc_rag.contracts import AskRequest, AskResponse, Pipeline
from multimodal_doc_rag.models.adapters import (
    OpenRouterEmbedder,
    OpenRouterGenerator,
    OpenRouterReranker,
)
from multimodal_doc_rag.models.openrouter import OpenRouterClient
from multimodal_doc_rag.pipeline import RagPipeline

# Why a lazily created module-level pool: `/health` and most tests must work with no
# database, so the pool is not opened at import or at startup. The first `/ask` that
# actually needs a connection creates it (under a lock, since FastAPI runs sync
# dependencies in a thread pool), and the lifespan below closes it on shutdown.
_pool: ConnectionPool[Any] | None = None
_pool_lock = threading.Lock()


def _configure(conn: psycopg.Connection[Any]) -> None:
    """Runs once per new pooled connection: teach it the pgvector type."""
    register_vector(conn)
    conn.commit()  # the pool requires a connection handed back in the idle state


def _get_pool() -> ConnectionPool[Any]:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(
                settings.database_url.get_secret_value(),
                min_size=1,
                max_size=4,
                configure=_configure,
                open=True,
            )
        return _pool


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


app = FastAPI(title="multimodal-doc-rag", lifespan=lifespan)

MAX_ANSWER_TOKENS = 600  # output cap: also a cost guard for the live demo


def _require_api_key() -> None:
    if settings.openrouter_api_key is None:
        raise HTTPException(
            status_code=503, detail="pipeline not configured: OPENROUTER_API_KEY is not set"
        )


def get_db_conn(_: None = Depends(_require_api_key)) -> Iterator[psycopg.Connection[Any]]:  # noqa: B008
    """Yield one pooled connection per request; it goes back to the pool afterwards.

    Depending on `_require_api_key` first means an unconfigured server answers 503 without
    ever touching the database.
    """
    with _get_pool().connection() as conn:  # commits (or rolls back on error) on exit
        yield conn


def get_pipeline(
    conn: psycopg.Connection[Any] = Depends(get_db_conn),  # noqa: B008
) -> Iterator[Pipeline]:
    """Dependency that supplies the pipeline to `/ask`.

    Dependency injection: the route does not build its own pipeline, it declares
    `Depends(get_pipeline)` and FastAPI calls this per request. Tests replace it (and
    `get_db_conn`) via `app.dependency_overrides`, e.g. to hand the pipeline the test's own
    transaction-bound connection.
    """
    client = OpenRouterClient.from_settings()
    try:
        yield RagPipeline(
            conn,
            embedder=OpenRouterEmbedder.from_settings(settings, client),
            reranker=OpenRouterReranker(client, settings.rerank_model),
            generator=OpenRouterGenerator(client, settings.generation_model, MAX_ANSWER_TOKENS),
        )
    finally:
        client.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# exclude_none: optional fields (page_end, image_url) are absent, not null.
@app.post("/ask", response_model=AskResponse, response_model_exclude_none=True)
def ask(
    request: AskRequest,
    pipeline: Pipeline = Depends(get_pipeline),  # noqa: B008
) -> AskResponse:
    return pipeline.ask(request)
