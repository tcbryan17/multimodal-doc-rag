"""A thin OpenRouter HTTP client (embeddings, rerank, chat). See ADR 0002 and 0009."""

import base64
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self

import httpx2
from pydantic import SecretStr

from multimodal_doc_rag.config import settings
from multimodal_doc_rag.models.cost import CostMeter

EMBED_BATCH_SIZE = 64
MAX_RETRIES = 2  # so at most 3 attempts in total
BACKOFF_BASE_S = 0.5

# ADR 0009: strict zero data retention, enforced in two layers. Layer 1 is the OpenRouter
# account setting; layer 2 is this payload, added to EVERY request in _post(). Either layer
# alone is enough to stop a leak, so a misconfigured account or a code mistake can't expose
# data on its own. Do not bypass _post(). A test checks every public method.
# docs/decisions/0009-models-and-privacy.md
PRIVACY_PROVIDER: dict[str, Any] = {"zdr": True, "data_collection": "deny"}


class OpenRouterError(Exception):
    """A failed OpenRouter call. The message never contains the API key."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ChatResult:
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost: float | None = None


def image_part(png: bytes) -> dict[str, Any]:
    """An OpenAI-format message part carrying a PNG as a base64 data URI."""
    b64 = base64.b64encode(png).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}


def _error_message(resp: httpx2.Response) -> str:
    try:
        msg = resp.json()["error"]["message"]
        if isinstance(msg, str):
            return msg
    except (ValueError, KeyError, TypeError):
        pass
    return resp.text[:200]


class OpenRouterClient:
    def __init__(
        self,
        api_key: SecretStr,
        base_url: str,
        timeout: float,
        transport: httpx2.BaseTransport | None = None,
        referer: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        meter: CostMeter | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._sleep = sleep
        # Optional spend tracking + cap (models/cost.py). The API runs without one; ingest and
        # the eval runner always pass one.
        self.meter = meter
        headers = {
            # The only place the secret is unwrapped.
            "Authorization": f"Bearer {api_key.get_secret_value()}",
            "X-Title": "multimodal-doc-rag",
        }
        if referer:
            headers["HTTP-Referer"] = referer
        self._http = httpx2.Client(headers=headers, timeout=timeout, transport=transport)

    @classmethod
    def from_settings(cls, meter: CostMeter | None = None) -> Self:
        if settings.openrouter_api_key is None:
            raise OpenRouterError("OPENROUTER_API_KEY is not set; add it to .env")
        return cls(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            timeout=settings.openrouter_timeout_s,
            meter=meter,
        )

    def __repr__(self) -> str:
        return f"OpenRouterClient(base_url={self._base_url!r})"

    def close(self) -> None:
        self._http.close()

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = {**body, "provider": dict(PRIVACY_PROVIDER)}
        url = f"{self._base_url}{path}"
        if self.meter is not None:
            self.meter.check()  # raises BudgetExceededError before spending any more
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self._http.post(url, json=payload)
            except httpx2.TimeoutException as exc:
                raise OpenRouterError(f"request to {path} timed out") from exc
            except httpx2.TransportError as exc:
                raise OpenRouterError(
                    f"network error calling {path}: {type(exc).__name__}"
                ) from exc
            retryable = resp.status_code == 429 or resp.status_code >= 500
            if retryable and attempt < MAX_RETRIES:
                self._sleep(BACKOFF_BASE_S * 2**attempt)
                continue
            if resp.status_code >= 400:
                raise OpenRouterError(
                    f"OpenRouter {path} failed ({resp.status_code}): {_error_message(resp)}",
                    status=resp.status_code,
                )
            try:
                data = resp.json()
            except ValueError as exc:
                raise OpenRouterError(f"non-JSON response from {path}") from exc
            if not isinstance(data, dict):
                raise OpenRouterError(f"unexpected response shape from {path}")
            if self.meter is not None:
                self.meter.record(body.get("model"), data.get("usage"))
            return data
        raise AssertionError("unreachable")  # pragma: no cover

    def embed(
        self, model: str, texts: list[str], dimensions: int | None = None
    ) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[start : start + EMBED_BATCH_SIZE]
            body: dict[str, Any] = {"model": model, "input": batch}
            if dimensions is not None:
                body["dimensions"] = dimensions
            data = self._post("/embeddings", body)
            try:
                items = sorted(data["data"], key=lambda d: d["index"])
                vectors = [[float(x) for x in d["embedding"]] for d in items]
            except (KeyError, TypeError) as exc:
                raise OpenRouterError("malformed embeddings response") from exc
            if len(vectors) != len(batch):
                raise OpenRouterError("embeddings response length does not match input")
            out.extend(vectors)
        return out

    def rerank(
        self, model: str, query: str, documents: list[str], top_n: int | None = None
    ) -> list[tuple[int, float]]:
        body: dict[str, Any] = {"model": model, "query": query, "documents": documents}
        if top_n is not None:
            body["top_n"] = top_n
        data = self._post("/rerank", body)
        try:
            pairs = [(int(r["index"]), float(r["relevance_score"])) for r in data["results"]]
        except (KeyError, TypeError) as exc:
            raise OpenRouterError("malformed rerank response") from exc
        return sorted(pairs, key=lambda p: p[1], reverse=True)

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float = 0.0,
    ) -> ChatResult:
        data = self._post(
            "/chat/completions",
            {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                # Ask OpenRouter to report the call's price in `usage.cost` (the cost meter
                # prefers a reported price over its own estimate).
                "usage": {"include": True},
            },
        )
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError("malformed chat response") from exc
        usage = data.get("usage") or {}
        return ChatResult(
            text=text,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            cost=usage.get("cost"),
        )
