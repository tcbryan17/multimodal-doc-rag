"""HTTP API: `/health`, `/ask`, `/figures` and `/stats` (contract in README and ADR 0005).

Live-hardening layers, outermost first: CORS (so browsers can read even error replies), the
request counters, then per-route guards: per-IP rate limit, daily spend cap, API-key check.
"""

import hmac
import logging
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Path, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from multimodal_doc_rag.config import settings
from multimodal_doc_rag.contracts import AskRequest, AskResponse, Pipeline
from multimodal_doc_rag.fakes import IDK
from multimodal_doc_rag.models.adapters import (
    OpenRouterEmbedder,
    OpenRouterGenerator,
    OpenRouterReranker,
)
from multimodal_doc_rag.models.cost import BudgetExceededError, Price
from multimodal_doc_rag.models.openrouter import OpenRouterClient, OpenRouterError
from multimodal_doc_rag.pipeline import RagPipeline
from multimodal_doc_rag.ratelimit import SlidingWindowLimiter, client_ip
from multimodal_doc_rag.search import fetch_figure_pngs
from multimodal_doc_rag.spend import DailyCostMeter
from multimodal_doc_rag.stats import Stats

log = logging.getLogger("multimodal_doc_rag.api")


@dataclass
class Ops:
    """The live-hardening state, one per process. Tests swap in their own via `api.ops`."""

    ask_limiter: SlidingWindowLimiter
    figures_limiter: SlidingWindowLimiter
    meter: DailyCostMeter
    stats: Stats

    @classmethod
    def from_settings(cls) -> "Ops":
        return cls(
            ask_limiter=SlidingWindowLimiter(
                settings.rate_limit_per_minute, settings.rate_limit_per_day
            ),
            figures_limiter=SlidingWindowLimiter(settings.figures_rate_limit_per_minute),
            meter=DailyCostMeter(
                cap_usd=settings.daily_spend_cap_usd,
                prices={m: Price(i, o) for m, (i, o) in settings.model_prices.items()},
                unpriced_call_usd=settings.unpriced_call_usd,
            ),
            stats=Stats(),
        )


ops = Ops.from_settings()

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


@app.middleware("http")
async def count_requests(request: Request, call_next: Any) -> Response:
    """Feed the /stats counters. Counts only; it never looks at bodies or query text."""
    if request.url.path == "/stats":
        # Monitoring polls must not inflate the numbers they report.
        passthrough: Response = await call_next(request)
        return passthrough
    try:
        response: Response = await call_next(request)
    except Exception:
        ops.stats.count_response(500)  # an unhandled error is a 500 even though we re-raise
        raise
    ops.stats.count_response(response.status_code)
    return response


def install_cors(target: FastAPI, origins: list[str]) -> None:
    """Allow the portfolio site's origin to call the API from the browser.

    No origins = add nothing, so a default deployment sends no CORS headers. GET and POST
    only (that is all the API has), no credentials (we use no cookies), and `Retry-After`
    is exposed so the site's JavaScript can tell a visitor when to try again. Added after
    the counting middleware, so it wraps it: even 429 and 503 replies carry CORS headers,
    otherwise the browser would hide them behind an opaque network error.
    """
    if not origins:
        return
    target.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["Retry-After"],
        allow_credentials=False,
        max_age=600,
    )


install_cors(app, settings.cors_origins)


@app.exception_handler(OpenRouterError)
def model_provider_error(_: Request, exc: OpenRouterError) -> JSONResponse:
    """A model provider failure (embedding or generation) is an upstream problem: answer 502
    with a generic message instead of a bare 500. The rerank step already degrades on its own,
    and OpenRouterError messages never contain the API key, but we still don't echo them."""
    return JSONResponse(status_code=502, content={"detail": "model provider unavailable"})


@app.exception_handler(BudgetExceededError)
def daily_budget_reached(_: Request, exc: BudgetExceededError) -> JSONResponse:
    """The cap tripped *during* a request (the pre-check in `require_daily_budget` passed
    just before it filled). Same reply as the pre-check; the message omits the dollar figures."""
    ops.stats.incr("budget_blocked")
    return _budget_response()


def _budget_response() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": "daily demo budget reached; try again tomorrow (UTC)"},
        headers={"Retry-After": str(ops.meter.seconds_until_reset())},
    )


def _limited(decision_retry_s: int, scope: str) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=f"too many {scope} requests from this address; try again in {decision_retry_s}s",
        headers={"Retry-After": str(decision_retry_s)},
    )


def rate_limit_ask(request: Request) -> None:
    decision = ops.ask_limiter.check(client_ip(request, settings.trusted_proxy_hops))
    if not decision.allowed:
        ops.stats.incr("rate_limited")
        raise _limited(decision.retry_after_s, "/ask")


def rate_limit_figures(request: Request) -> None:
    decision = ops.figures_limiter.check(client_ip(request, settings.trusted_proxy_hops))
    if not decision.allowed:
        ops.stats.incr("rate_limited")
        raise _limited(decision.retry_after_s, "/figures")


def require_daily_budget() -> None:
    """Refuse `/ask` up front once today's cap is spent, before touching the DB or models."""
    if ops.meter.exhausted():
        ops.stats.incr("budget_blocked")
        raise HTTPException(
            status_code=503,
            detail="daily demo budget reached; try again tomorrow (UTC)",
            headers={"Retry-After": str(ops.meter.seconds_until_reset())},
        )


# Output cap, also a cost guard for the live demo. Raised from 600 (ADR 0015): with hidden
# reasoning on, the reasoning alone could use up 600. Reasoning is off by default.
MAX_ANSWER_TOKENS = 1200


def _require_api_key() -> None:
    if settings.openrouter_api_key is None:
        raise HTTPException(
            status_code=503, detail="pipeline not configured: OPENROUTER_API_KEY is not set"
        )


def get_db_conn() -> Iterator[psycopg.Connection[Any]]:
    """Yield one pooled connection per request; it goes back to the pool afterwards.

    Deliberately independent of the model key: `/figures` only reads the database and must
    work without one. The key check lives on `get_pipeline` instead.
    """
    with _get_pool().connection() as conn:  # commits (or rolls back on error) on exit
        yield conn


def build_pipeline(conn: psycopg.Connection[Any], client: OpenRouterClient) -> RagPipeline:
    """The real pipeline over a connection and client. Shared with scripts/save_replay.py so the
    recorded replay comes from exactly the pipeline the API serves."""
    return RagPipeline(
        conn,
        embedder=OpenRouterEmbedder.from_settings(settings, client),
        reranker=OpenRouterReranker(client, settings.rerank_model),
        generator=OpenRouterGenerator(
            client,
            settings.generation_model,
            MAX_ANSWER_TOKENS,
            reasoning=settings.generation_reasoning,
        ),
    )


def get_pipeline(
    # FastAPI resolves dependencies in parameter order, so the key check runs first: with no
    # key `/ask` answers 503 without ever touching the database.
    _: None = Depends(_require_api_key),  # noqa: B008
    conn: psycopg.Connection[Any] = Depends(get_db_conn),  # noqa: B008
) -> Iterator[Pipeline]:
    """Dependency that supplies the pipeline to `/ask`.

    Dependency injection: the route does not build its own pipeline, it declares
    `Depends(get_pipeline)` and FastAPI calls this per request. Tests replace it (and
    `get_db_conn`) via `app.dependency_overrides`, e.g. to hand the pipeline the test's own
    transaction-bound connection.
    """
    # The shared meter makes every model call count against (and be stopped by) the daily cap.
    client = OpenRouterClient.from_settings(meter=ops.meter)
    try:
        yield build_pipeline(conn, client)
    finally:
        client.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# exclude_none: optional fields (page_end, image_url) are absent, not null.
# Route-level dependencies run before the parameter ones, in this order: rate limit, budget,
# then the API-key check inside get_pipeline. Abusers are turned away before anything costs.
@app.post(
    "/ask",
    response_model=AskResponse,
    response_model_exclude_none=True,
    dependencies=[Depends(rate_limit_ask), Depends(require_daily_budget)],
)
def ask(
    request: AskRequest,
    pipeline: Pipeline = Depends(get_pipeline),  # noqa: B008
) -> AskResponse:
    t0 = time.perf_counter()
    response = pipeline.ask(request)
    latency_ms = int((time.perf_counter() - t0) * 1000)
    is_idk = response.answer.strip() == IDK
    ops.stats.incr("asks")
    ops.stats.incr("ask_latency_ms_total", latency_ms)
    if is_idk:
        ops.stats.incr("idk_answers")
    # C20 (owner's decision, ADR 0021): log only counts and latency, never what was asked.
    log.info(
        "ask ok latency_ms=%d citations=%d idk=%s", latency_ms, len(response.citations), is_idk
    )
    return response


@app.get("/stats")
def stats(request: Request) -> dict[str, object]:
    """Monitoring counters (C27), behind a bearer token. No token configured = 404, so the
    endpoint does not exist on a deployment that never opted in."""
    token = settings.stats_token
    if token is None:
        raise HTTPException(status_code=404, detail="Not Found")
    supplied = request.headers.get("authorization", "")
    expected = f"Bearer {token.get_secret_value()}"
    # compare_digest: constant-time, so response timing can't be used to guess the token.
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(
            status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"}
        )
    return {
        **ops.stats.snapshot(),
        "spend_today_usd": round(ops.meter.spent_today(), 6),
        "daily_spend_cap_usd": ops.meter.cap_usd,
    }


# Chunk ids are identity columns and are never reused, and a figure's PNG is written once at
# ingest, so the bytes behind a given URL never change. Hence "immutable" and a one-year
# max-age: browsers and CDNs may keep it forever.
FIGURE_CACHE_CONTROL = "public, max-age=31536000, immutable"


@app.get("/figures/{chunk_id}.png", dependencies=[Depends(rate_limit_figures)])
def figure(
    chunk_id: int = Path(gt=0),
    conn: psycopg.Connection[Any] = Depends(get_db_conn),  # noqa: B008
) -> Response:
    png = fetch_figure_pngs(conn, [chunk_id]).get(chunk_id)
    if png is None:
        raise HTTPException(status_code=404, detail="figure not found")
    return Response(
        content=png, media_type="image/png", headers={"Cache-Control": FIGURE_CACHE_CONTROL}
    )
