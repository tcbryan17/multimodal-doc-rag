"""OpenRouter client tests. No network: httpx2.MockTransport answers every request."""

import base64
import json
import math
import os
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from multimodal_doc_rag.config import settings
from multimodal_doc_rag.models.openrouter import (
    OpenRouterClient,
    OpenRouterError,
    image_part,
)
from multimodal_doc_rag.models.vectors import truncate_and_normalize

KEY = "sk-or-test-SECRET-123"
BASE = "https://example.test/api/v1"

Handler = Callable[[httpx2.Request], httpx2.Response]


class Recorder:
    """Wraps a handler, remembering every request it sees."""

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx2.Request] = []
        self.sleeps: list[float] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.handler(request)

    def body(self, i: int = -1) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self.requests[i].content)
        return result


def make(handler: Handler) -> tuple[OpenRouterClient, Recorder]:
    rec = Recorder(handler)
    client = OpenRouterClient(
        api_key=SecretStr(KEY),
        base_url=BASE,
        timeout=5.0,
        transport=httpx2.MockTransport(rec),
        sleep=rec.sleeps.append,
    )
    return client, rec


def ok_handler(request: httpx2.Request) -> httpx2.Response:
    path = request.url.path
    body = json.loads(request.content)
    if path.endswith("/embeddings"):
        data = [{"index": i, "embedding": [float(i), 1.0]} for i in range(len(body["input"]))]
        return httpx2.Response(200, json={"data": data[::-1]})  # shuffled on purpose
    if path.endswith("/rerank"):
        results = [{"index": 0, "relevance_score": 0.1}, {"index": 1, "relevance_score": 0.9}]
        return httpx2.Response(200, json={"results": results})
    return httpx2.Response(
        200,
        json={
            "choices": [{"message": {"content": "hi"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "cost": 0.001},
        },
    )


def call_embed(c: OpenRouterClient) -> object:
    return c.embed("m", ["a", "b"])


def call_rerank(c: OpenRouterClient) -> object:
    return c.rerank("m", "q", ["a", "b"])


def call_chat(c: OpenRouterClient) -> object:
    return c.chat("m", [{"role": "user", "content": "x"}], max_tokens=10)


# Add every new client method here so the privacy check covers it.
ALL_METHODS = [call_embed, call_rerank, call_chat]


@pytest.mark.parametrize("call", ALL_METHODS)
def test_every_request_demands_zdr_and_no_data_collection(
    call: Callable[[OpenRouterClient], object],
) -> None:
    client, rec = make(ok_handler)
    call(client)
    assert rec.requests
    for i in range(len(rec.requests)):
        assert rec.body(i)["provider"] == {"zdr": True, "data_collection": "deny"}


def test_headers_and_key_not_leaked() -> None:
    client, rec = make(ok_handler)
    client.chat("m", [], max_tokens=1)
    req = rec.requests[0]
    assert req.headers["Authorization"] == f"Bearer {KEY}"
    assert req.headers["X-Title"] == "multimodal-doc-rag"
    assert KEY not in repr(client) and KEY not in str(client)

    failing, _ = make(lambda r: httpx2.Response(400, json={"error": {"message": "bad"}}))
    with pytest.raises(OpenRouterError) as exc:
        failing.chat("m", [], max_tokens=1)
    assert KEY not in repr(exc.value) and KEY not in str(exc.value)


def test_embed_preserves_order_despite_shuffled_response() -> None:
    client, _ = make(ok_handler)
    vecs = client.embed("m", ["a", "b", "c"])
    assert vecs == [[0.0, 1.0], [1.0, 1.0], [2.0, 1.0]]


def test_embed_batches_and_passes_dimensions() -> None:
    client, rec = make(ok_handler)
    vecs = client.embed("m", [str(i) for i in range(150)], dimensions=1024)
    assert [len(rec.body(i)["input"]) for i in range(len(rec.requests))] == [64, 64, 22]
    assert all(rec.body(i)["dimensions"] == 1024 for i in range(3))
    assert len(vecs) == 150


def test_rerank_sorted_by_score_desc() -> None:
    client, rec = make(ok_handler)
    assert client.rerank("m", "q", ["a", "b"], top_n=2) == [(1, 0.9), (0, 0.1)]
    assert rec.body()["top_n"] == 2


def test_chat_result_with_usage() -> None:
    client, _ = make(ok_handler)
    res = client.chat("m", [{"role": "user", "content": "x"}], max_tokens=5)
    assert (res.text, res.prompt_tokens, res.completion_tokens, res.cost) == ("hi", 3, 1, 0.001)


def test_retry_on_429_then_success() -> None:
    calls = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx2.Response(429, json={"error": {"message": "slow down"}})
        return ok_handler(request)

    client, rec = make(handler)
    assert client.chat("m", [], max_tokens=1).text == "hi"
    assert calls["n"] == 2
    assert len(rec.sleeps) == 1


def test_persistent_500_raises_after_three_attempts() -> None:
    client, rec = make(lambda r: httpx2.Response(500, json={"error": {"message": "boom"}}))
    with pytest.raises(OpenRouterError, match="boom") as exc:
        client.chat("m", [], max_tokens=1)
    assert exc.value.status == 500
    assert len(rec.requests) == 3
    assert len(rec.sleeps) == 2


def test_400_is_not_retried() -> None:
    client, rec = make(lambda r: httpx2.Response(400, json={"error": {"message": "nope"}}))
    with pytest.raises(OpenRouterError, match="nope") as exc:
        client.chat("m", [], max_tokens=1)
    assert exc.value.status == 400
    assert len(rec.requests) == 1
    assert rec.sleeps == []


def test_timeout_raises_openrouter_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    client, _ = make(handler)
    with pytest.raises(OpenRouterError, match="timed out"):
        client.chat("m", [], max_tokens=1)


def test_from_settings_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    with pytest.raises(OpenRouterError, match="OPENROUTER_API_KEY"):
        OpenRouterClient.from_settings()
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr(KEY))
    assert isinstance(OpenRouterClient.from_settings(), OpenRouterClient)


def test_truncate_and_normalize() -> None:
    out = truncate_and_normalize([3.0, 4.0, 100.0], 2)
    assert len(out) == 2
    assert math.isclose(math.sqrt(sum(x * x for x in out)), 1.0)
    assert out == pytest.approx([0.6, 0.8])


@pytest.mark.parametrize(("vec", "dim"), [([1.0, 2.0], 3), ([0.0, 0.0, 1.0], 2), ([1.0], 0)])
def test_truncate_and_normalize_rejects_bad_input(vec: list[float], dim: int) -> None:
    with pytest.raises(ValueError):
        truncate_and_normalize(vec, dim)


def test_image_part_builds_data_uri() -> None:
    part = image_part(b"\x89PNGdata")
    assert part["type"] == "image_url"
    url = part["image_url"]["url"]
    prefix = "data:image/png;base64,"
    assert url.startswith(prefix)
    assert base64.b64decode(url[len(prefix) :]) == b"\x89PNGdata"


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY not set")
def test_live_embed() -> None:
    client = OpenRouterClient.from_settings()
    vecs = client.embed(settings.embedding_model, ["hello"], dimensions=settings.embedding_dim)
    assert len(vecs) == 1 and len(vecs[0]) == settings.embedding_dim
