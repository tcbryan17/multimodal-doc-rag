"""Live OpenRouter checks (cost real money, so `-m live` only; skipped with no key).

These verify behaviours no mock can: whether the provider honours `dimensions`, the real rerank
response shape, image input under zero-data-retention, and whether usage.cost is reported.
Several RECORD a fact rather than assert it (see `record_property` and `-s` output): the answer
is information for the owner, not a pass/fail condition. `scripts/ingest_corpus.py
--preflight-only` reports the same facts without pytest.

The key is read through Settings (which reads .env), not os.environ: a key that lives only in
.env must not make these skip silently.
"""

from collections.abc import Callable

import pytest

from multimodal_doc_rag.config import Settings
from multimodal_doc_rag.models.adapters import OpenRouterEmbedder, OpenRouterReranker
from multimodal_doc_rag.models.cost import CostMeter, Price
from multimodal_doc_rag.models.openrouter import OpenRouterClient, image_part

pytestmark = pytest.mark.live

# Smallest valid PNG (1x1 transparent pixel).
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)


def live_client() -> tuple[OpenRouterClient, Settings, CostMeter]:
    s = Settings()
    if s.openrouter_api_key is None:
        pytest.skip("OPENROUTER_API_KEY not set")
    meter = CostMeter(
        0.25,
        prices={m: Price(*p) for m, p in s.model_prices.items()},
        unpriced_call_usd=s.unpriced_call_usd,
    )
    return OpenRouterClient.from_settings(meter=meter), s, meter


def test_live_embed_dimensions(record_property: Callable[[str, object], None]) -> None:
    client, s, _ = live_client()
    raw = client.embed(s.embedding_model, ["hello"], dimensions=s.embedding_dim)
    honoured = len(raw[0]) == s.embedding_dim
    record_property("provider_honoured_dimensions", honoured)
    print(f"\nraw embedding length {len(raw[0])}; provider honoured `dimensions`: {honoured}")
    # Either way, what we STORE must be the configured size and unit length.
    stored = OpenRouterEmbedder.from_settings(s, client).embed_documents(["hello"])[0]
    assert len(stored) == s.embedding_dim
    assert sum(x * x for x in stored) == pytest.approx(1.0, rel=1e-6)


def test_live_rerank_response_shape() -> None:
    client, s, _ = live_client()
    docs = ["Revenue grew 6%.", "The altimeter measures altitude.", "Stalls are a loss of lift."]
    raw = client.rerank(s.rerank_model, "what does an altimeter measure", docs, top_n=3)
    assert raw and all(0 <= i < len(docs) and isinstance(score, float) for i, score in raw)
    ranked = OpenRouterReranker(client, s.rerank_model).rerank("altimeter", docs, top_n=2)
    assert len(ranked) == 2 and ranked[0][1] >= ranked[1][1]


def test_live_chat_with_image_part_under_zdr() -> None:
    client, s, _ = live_client()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Reply with the single word: ok"},
                image_part(TINY_PNG),
            ],
        }
    ]
    result = client.chat(s.vision_model, messages, max_tokens=20)
    assert result.text.strip()


def test_live_usage_cost_is_reported(record_property: Callable[[str, object], None]) -> None:
    """Record, don't assert: does OpenRouter send usage.cost for chat, embeddings and rerank?"""
    client, s, meter = live_client()
    seen: dict[str, str] = {}

    def source() -> tuple[int, int, int]:
        return (meter.reported_calls, meter.estimated_calls, meter.unpriced_calls)

    calls: dict[str, Callable[[], object]] = {
        "chat": lambda: client.chat(s.vision_model, [{"role": "user", "content": "hi"}], 5),
        "embeddings": lambda: client.embed(s.embedding_model, ["hi"], dimensions=s.embedding_dim),
        "rerank": lambda: client.rerank(s.rerank_model, "q", ["a", "b"], top_n=1),
    }
    for name, call in calls.items():
        before = source()
        call()
        after = source()
        seen[name] = ("reported", "estimated", "unpriced")[
            next(i for i in range(3) if after[i] > before[i])
        ]
        record_property(f"cost_source_{name}", seen[name])
    print(f"\ncost source per endpoint: {seen}; {meter.summary()}")
