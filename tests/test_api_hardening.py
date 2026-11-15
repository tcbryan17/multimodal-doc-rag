"""Live-API hardening (controls C26, C27, C20, plus input caps), all with fakes: no model key,
no database."""

import logging
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from multimodal_doc_rag import api
from multimodal_doc_rag.api import app, get_db_conn, get_pipeline, install_cors
from multimodal_doc_rag.config import Settings, settings
from multimodal_doc_rag.contracts import MAX_QUESTION_LENGTH, AskRequest, AskResponse
from multimodal_doc_rag.fakes import IDK
from multimodal_doc_rag.models.openrouter import OpenRouterClient
from multimodal_doc_rag.ratelimit import SlidingWindowLimiter
from multimodal_doc_rag.spend import DailyCostMeter
from multimodal_doc_rag.stats import Stats

SITE = "https://tcbryan17.github.io"


class FakePipeline:
    """Answers, and charges the shared meter like the real client would."""

    def __init__(self, answer: str = "42", cost: float = 0.0) -> None:
        self.answer = answer
        self.cost = cost

    def ask(self, request: AskRequest) -> AskResponse:
        api.ops.meter.check()
        api.ops.meter.record("m", {"cost": self.cost})
        return AskResponse(answer=self.answer, citations=[], trace=[])


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def _use(pipeline: FakePipeline) -> None:
    app.dependency_overrides[get_pipeline] = lambda: pipeline


def _strict_ops(
    monkeypatch: pytest.MonkeyPatch, per_minute: int = 2, per_day: int = 100, cap: float = 1.0
) -> None:
    ops = api.Ops(
        ask_limiter=SlidingWindowLimiter(per_minute, per_day),
        figures_limiter=SlidingWindowLimiter(120),
        meter=DailyCostMeter(cap_usd=cap),
        stats=Stats(),
    )
    monkeypatch.setattr(api, "ops", ops)


# --- CORS -------------------------------------------------------------------------------


def test_cors_default_is_off() -> None:
    assert Settings(_env_file=None).cors_origins == []  # type: ignore[call-arg]
    bare = FastAPI()
    install_cors(bare, [])
    assert bare.user_middleware == []


def test_cors_allows_only_the_configured_origin_and_get_post() -> None:
    site = FastAPI()

    @site.post("/ask")
    def _ask() -> dict[str, str]:
        return {"ok": "1"}

    install_cors(site, [SITE])
    c = TestClient(site)
    pre = c.options(
        "/ask",
        headers={
            "Origin": SITE,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert pre.status_code == 200
    assert pre.headers["access-control-allow-origin"] == SITE
    assert set(pre.headers["access-control-allow-methods"].split(", ")) == {"GET", "POST"}
    assert "access-control-allow-credentials" not in pre.headers
    other = c.options(
        "/ask", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in other.headers
    delete = c.options("/ask", headers={"Origin": SITE, "Access-Control-Request-Method": "DELETE"})
    assert delete.status_code == 400


def test_cors_origins_setting_parses_comma_list_and_trailing_slash() -> None:
    s = Settings(_env_file=None, cors_allow_origins=f" {SITE}/ , http://localhost:4000 ")  # type: ignore[call-arg]
    assert s.cors_origins == [SITE, "http://localhost:4000"]


# --- Rate limiting ----------------------------------------------------------------------


def test_ask_is_rate_limited_per_ip_with_429_and_retry_after(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strict_ops(monkeypatch, per_minute=2)
    _use(FakePipeline())
    assert client.post("/ask", json={"question": "a"}).status_code == 200
    assert client.post("/ask", json={"question": "a"}).status_code == 200
    r = client.post("/ask", json={"question": "a"})
    assert r.status_code == 429
    assert "too many" in r.json()["detail"]
    assert 1 <= int(r.headers["retry-after"]) <= 60
    assert api.ops.stats.snapshot()["since_start"]["rate_limited"] == 1  # type: ignore[index]


def test_spoofed_forwarded_header_cannot_dodge_the_limit_by_default(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strict_ops(monkeypatch, per_minute=1)
    _use(FakePipeline())
    assert client.post("/ask", json={"question": "a"}, headers={"X-Forwarded-For": "1.1.1.1"})
    r = client.post("/ask", json={"question": "a"}, headers={"X-Forwarded-For": "2.2.2.2"})
    assert r.status_code == 429


def test_trusted_proxy_hops_separates_real_visitors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strict_ops(monkeypatch, per_minute=1)
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    _use(FakePipeline())

    def ask(visitor: str) -> int:
        # A forged leftmost entry is ignored; the proxy-appended rightmost one is the bucket.
        return client.post(
            "/ask", json={"question": "a"}, headers={"X-Forwarded-For": f"9.9.9.9, {visitor}"}
        ).status_code

    assert ask("203.0.113.1") == 200
    assert ask("203.0.113.2") == 200
    assert ask("203.0.113.1") == 429


def test_health_is_never_limited_and_figures_have_their_own_limiter(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strict_ops(monkeypatch, per_minute=1)
    for _ in range(20):
        assert client.get("/health").status_code == 200
    # /figures uses figures_limiter, not the /ask bucket: with /ask exhausted it is untouched.
    _use(FakePipeline())
    client.post("/ask", json={"question": "a"})
    assert client.post("/ask", json={"question": "a"}).status_code == 429
    assert api.ops.figures_limiter.check("testclient").allowed


def test_figures_limit_returns_429(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _strict_ops(monkeypatch)
    api.ops.figures_limiter = SlidingWindowLimiter(1)
    app.dependency_overrides[get_db_conn] = lambda: None
    monkeypatch.setattr(api, "fetch_figure_pngs", lambda conn, ids: {1: b"png"})
    assert client.get("/figures/1.png").status_code == 200
    r = client.get("/figures/1.png")
    assert r.status_code == 429
    assert "retry-after" in r.headers


# --- Daily spend cap --------------------------------------------------------------------


def test_ask_returns_503_once_the_daily_cap_is_reached_and_health_still_works(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strict_ops(monkeypatch, per_minute=100, cap=1.0)
    _use(FakePipeline(cost=0.6))
    assert client.post("/ask", json={"question": "a"}).status_code == 200  # spent 0.6
    assert client.post("/ask", json={"question": "a"}).status_code == 200  # spent 1.2 >= cap
    r = client.post("/ask", json={"question": "a"})
    assert r.status_code == 503
    assert "daily demo budget reached" in r.json()["detail"]
    assert int(r.headers["retry-after"]) >= 1
    assert client.get("/health").json() == {"status": "ok"}


def test_cap_tripping_mid_request_is_also_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strict_ops(monkeypatch, cap=0.5)

    class FillsThenFails(FakePipeline):
        def ask(self, request: AskRequest) -> AskResponse:
            api.ops.meter.record("m", {"cost": 0.9})
            api.ops.meter.check()  # what the OpenRouter client does before its next call
            raise AssertionError("unreachable")

    _use(FillsThenFails())
    r = client.post("/ask", json={"question": "a"})
    assert r.status_code == 503
    assert "daily demo budget reached" in r.json()["detail"]


def test_real_client_is_built_with_the_shared_meter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr("sk-test"))
    seen: list[OpenRouterClient] = []

    def fake_build(conn: object, c: OpenRouterClient) -> object:
        seen.append(c)
        return object()

    monkeypatch.setattr(api, "build_pipeline", fake_build)
    gen = api.get_pipeline(None, None)  # type: ignore[arg-type]
    next(gen)
    assert seen[0].meter is api.ops.meter
    gen.close()  # type: ignore[attr-defined]


def test_daily_cap_setting_feeds_the_meter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "daily_spend_cap_usd", 0.25)
    assert api.Ops.from_settings().meter.cap_usd == 0.25


# --- Input caps -------------------------------------------------------------------------


def test_question_length_cap_and_empty_input_are_422(client: TestClient) -> None:
    _use(FakePipeline())
    ok = client.post("/ask", json={"question": "x" * MAX_QUESTION_LENGTH})
    assert ok.status_code == 200
    for bad in ["x" * (MAX_QUESTION_LENGTH + 1), "", "   \n\t "]:
        assert client.post("/ask", json={"question": bad}).status_code == 422
    # Padding with spaces can't be used to dodge the cap nor to sneak in an empty question.
    assert AskRequest(question="  hi  " + " " * 5000).question == "hi"


def test_filter_fields_are_bounded() -> None:
    with pytest.raises(ValidationError):
        AskRequest(question="q", corpus="c" * 101)


# --- Stats ------------------------------------------------------------------------------


def test_stats_disabled_without_token(client: TestClient) -> None:
    assert settings.stats_token is None
    assert client.get("/stats").status_code == 404
    assert client.get("/stats", headers={"Authorization": "Bearer x"}).status_code == 404


def test_blank_stats_token_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STATS_TOKEN", "  ")
    assert Settings(_env_file=None).stats_token is None  # type: ignore[call-arg]


def test_stats_requires_the_bearer_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "stats_token", SecretStr("s3cret"))
    assert client.get("/stats").status_code == 401
    assert client.get("/stats", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/stats", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_stats_counts_requests_errors_idk_and_spend(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strict_ops(monkeypatch, per_minute=3, cap=10.0)
    monkeypatch.setattr(settings, "stats_token", SecretStr("t"))
    _use(FakePipeline(answer="42", cost=0.25))
    client.post("/ask", json={"question": "a"})  # 200
    _use(FakePipeline(answer=IDK, cost=0.25))
    client.post("/ask", json={"question": "a"})  # 200, idk
    client.post("/ask", json={"question": ""})  # 422 (4xx)
    client.post("/ask", json={"question": "a"})  # 429 (4xx, rate limited)
    client.get("/health")
    body = client.get("/stats", headers={"Authorization": "Bearer t"}).json()
    for scope in ("since_start", "today"):
        c = body[scope]
        assert c["requests"] == 5  # /stats itself is not counted
        assert c["client_errors"] == 2
        assert c["server_errors"] == 0
        assert c["rate_limited"] == 1
        assert c["asks"] == 2
        assert c["idk_answers"] == 1
    assert body["spend_today_usd"] == 0.5
    assert body["daily_spend_cap_usd"] == 10.0


def test_stats_counts_5xx_and_resets_today_at_utc_midnight(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    now = [datetime(2026, 11, 14, 23, 59, tzinfo=UTC)]
    stats = Stats(clock=lambda: now[0])
    stats.count_response(503)
    now[0] += timedelta(minutes=2)
    stats.count_response(200)
    snap = stats.snapshot()
    assert snap["since_start"]["server_errors"] == 1  # type: ignore[index]
    today: dict[str, object] = snap["today"]  # type: ignore[assignment]
    assert (today["date"], today["requests"], today["server_errors"]) == ("2026-11-15", 1, 0)


# --- Question logging (C20) -------------------------------------------------------------


def test_question_text_is_never_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """ADR 0021: no setting turns question logging on; logs carry counts and latency only."""
    assert not hasattr(Settings(_env_file=None), "log_questions")  # type: ignore[call-arg]
    _use(FakePipeline())
    with caplog.at_level(logging.DEBUG, logger="multimodal_doc_rag"):
        client.post("/ask", json={"question": "my secret question"})
    assert "secret" not in caplog.text
    assert "latency_ms=" in caplog.text


# --- Pre-deploy security review (ADR 0023) ----------------------------------------------


def test_interactive_docs_are_off_by_default() -> None:
    assert Settings().api_docs is False
    off = TestClient(api.create_app(api_docs=False))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert off.get(path).status_code == 404
    on = TestClient(api.create_app(api_docs=True))
    assert on.get("/openapi.json").status_code == 200


def test_the_served_app_follows_the_setting() -> None:
    paths = {getattr(r, "path", "") for r in app.routes}
    assert ("/openapi.json" in paths) is settings.api_docs


def test_oversized_body_is_refused_before_parsing(client: TestClient) -> None:
    _use(FakePipeline())
    big = '{"question": "' + "x" * (settings.max_body_bytes + 10) + '"}'
    r = client.post("/ask", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_body_without_content_length_is_refused(client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        yield b'{"question": "hi"}'

    r = client.post("/ask", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 411


def test_normal_ask_still_works_under_the_body_limit(client: TestClient) -> None:
    _use(FakePipeline())
    r = client.post("/ask", json={"question": "q" * MAX_QUESTION_LENGTH})
    assert r.status_code == 200


def test_security_headers_on_every_response(client: TestClient) -> None:
    for r in (client.get("/health"), client.get("/no-such-route")):
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "no-referrer"
        assert "max-age=" in r.headers["strict-transport-security"]
        assert r.headers["content-security-policy"].startswith("default-src 'none'")


def test_rejected_bodies_still_carry_cors_headers() -> None:
    target = api.create_app(api_docs=False)
    target.add_middleware(api.BodySizeLimit, max_bytes=1024)
    install_cors(target, [SITE])
    r = TestClient(target).post(
        "/ask", content="x" * 2000, headers={"Origin": SITE, "Content-Type": "application/json"}
    )
    assert r.status_code == 413
    assert r.headers["access-control-allow-origin"] == SITE


def test_exhausted_connection_pool_is_a_fast_503(client: TestClient) -> None:
    from psycopg_pool import PoolTimeout

    def busy() -> Iterator[None]:
        raise PoolTimeout("no connection available")
        yield  # pragma: no cover

    app.dependency_overrides[get_db_conn] = busy
    r = client.get("/figures/1.png")
    assert r.status_code == 503
    assert r.headers["retry-after"] == "5"
