"""Adapter tests through the real OpenRouterClient, with httpx2.MockTransport (no network)."""

import json
import math
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from multimodal_doc_rag.config import Settings
from multimodal_doc_rag.fakes import IDK
from multimodal_doc_rag.models.adapters import (
    DEFAULT_QUERY_TASK,
    FigureDescriptionError,
    OpenRouterEmbedder,
    OpenRouterFigureDescriber,
    OpenRouterGenerator,
    OpenRouterReranker,
)
from multimodal_doc_rag.models.openrouter import PRIVACY_PROVIDER, OpenRouterClient
from multimodal_doc_rag.types import FigureDescription, PageRef, Passage

PNG = b"\x89PNG-fake"

Handler = Callable[[httpx2.Request], httpx2.Response]


def make_client(handler: Handler) -> tuple[OpenRouterClient, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def wrapped(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        return handler(req)

    client = OpenRouterClient(
        SecretStr("k"), "https://example.test/api/v1", 5.0, httpx2.MockTransport(wrapped)
    )
    return client, seen


def body(req: httpx2.Request) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(req.content)
    return parsed


def embed_handler(vec_len: int) -> Handler:
    def handler(req: httpx2.Request) -> httpx2.Response:
        inputs = body(req)["input"]
        data = [
            {"index": i, "embedding": [3.0, 4.0] + [0.0] * (vec_len - 2)}
            for i in range(len(inputs))
        ]
        return httpx2.Response(200, json={"data": data})

    return handler


def chat_handler(text: str) -> Handler:
    return lambda req: httpx2.Response(200, json={"choices": [{"message": {"content": text}}]})


# --- embedder ---------------------------------------------------------------------------


def test_query_gets_instruction_documents_do_not() -> None:
    client, seen = make_client(embed_handler(8))
    emb = OpenRouterEmbedder(client, "m", 8)
    emb.embed_query("what is lift?")
    emb.embed_documents(["Lift is a force."])
    assert body(seen[0])["input"] == [f"Instruct: {DEFAULT_QUERY_TASK}\nQuery: what is lift?"]
    assert body(seen[1])["input"] == ["Lift is a force."]


def test_instruction_can_be_disabled_or_overridden() -> None:
    client, seen = make_client(embed_handler(8))
    OpenRouterEmbedder(client, "m", 8, query_instruction=None).embed_query("q")
    OpenRouterEmbedder(client, "m", 8, query_instruction="Find it").embed_query("q")
    assert body(seen[0])["input"] == ["q"]
    assert body(seen[1])["input"] == ["Instruct: Find it\nQuery: q"]


def test_dimensions_param_is_sent_and_zdr_fields_present() -> None:
    client, seen = make_client(embed_handler(8))
    OpenRouterEmbedder(client, "m", 8).embed_documents(["x"])
    assert body(seen[0])["dimensions"] == 8
    assert body(seen[0])["provider"] == PRIVACY_PROVIDER


def test_overlong_vectors_are_truncated_and_renormalised() -> None:
    client, _ = make_client(embed_handler(16))  # provider ignores `dimensions`
    (v,) = OpenRouterEmbedder(client, "m", 2).embed_documents(["x"])
    assert v == pytest.approx([0.6, 0.8])
    assert math.sqrt(sum(x * x for x in v)) == pytest.approx(1.0)


def test_too_short_vectors_raise() -> None:
    client, _ = make_client(embed_handler(4))
    with pytest.raises(ValueError, match="cannot truncate"):
        OpenRouterEmbedder(client, "m", 8).embed_documents(["x"])


def test_model_key_and_from_settings() -> None:
    client, _ = make_client(embed_handler(8))
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    emb = OpenRouterEmbedder.from_settings(s, client)
    assert emb.model_key == s.embedding_key
    assert emb.dim == s.embedding_dim
    assert OpenRouterEmbedder(client, "a/b", 8).model_key == "a/b@8"


def test_empty_batch_makes_no_call() -> None:
    client, seen = make_client(embed_handler(8))
    assert OpenRouterEmbedder(client, "m", 8).embed_documents([]) == []
    assert seen == []


# --- reranker ---------------------------------------------------------------------------


def test_rerank_orders_best_first_and_caps_top_n() -> None:
    def handler(req: httpx2.Request) -> httpx2.Response:
        results = [
            {"index": 0, "relevance_score": 0.1},
            {"index": 1, "relevance_score": 0.9},
            {"index": 2, "relevance_score": 0.5},
        ]
        return httpx2.Response(200, json={"results": results})

    client, seen = make_client(handler)
    out = OpenRouterReranker(client, "r").rerank("q", ["a", "b", "c"], top_n=2)
    assert out == [(1, 0.9), (2, 0.5)]
    assert body(seen[0])["top_n"] == 2


def test_rerank_empty_documents_makes_no_call() -> None:
    client, seen = make_client(chat_handler(""))
    assert OpenRouterReranker(client, "r").rerank("q", [], top_n=3) == []
    assert seen == []


# --- figure describer -------------------------------------------------------------------

CLEAN = '{"informational": true, "description": "Altimeter dial, 0-9 ft x1000"}'


def describe(reply: str) -> tuple[FigureDescription, list[httpx2.Request]]:
    client, seen = make_client(chat_handler(reply))
    return OpenRouterFigureDescriber(client, "v").describe(PNG, "Figure 1", "ctx"), seen


def test_describer_sends_image_caption_and_context() -> None:
    result, seen = describe(CLEAN)
    assert result.informational is True
    assert result.description.startswith("Altimeter dial")
    content = body(seen[0])["messages"][0]["content"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "Figure 1" in content[0]["text"] and "ctx" in content[0]["text"]
    assert "not instructions" in content[0]["text"]  # prompt-injection hygiene


def test_describer_parses_fenced_json_and_json_with_prose() -> None:
    fenced, _ = describe(f"```json\n{CLEAN}\n```")
    prose, _ = describe(f"Sure! Here you go: {CLEAN} Hope that helps {{not json}}")
    assert fenced.informational and prose.informational
    assert prose.description.startswith("Altimeter dial")


def test_describer_decorative_may_have_empty_description() -> None:
    result, _ = describe('{"informational": false, "description": ""}')
    assert result.informational is False
    assert result.description == ""


@pytest.mark.parametrize(
    "reply", ["I cannot help", "", "{broken", '{"informational": "yes", "description": "x"}']
)
def test_describer_garbage_raises(reply: str) -> None:
    with pytest.raises(FigureDescriptionError):
        describe(reply)


# ---- OpenRouterGenerator -------------------------------------------------------------


def _passage(chunk_id: int, content: str) -> Passage:
    page = PageRef(idx=1, label="8-4")
    return Passage(chunk_id, "doc", "Doc Title", "text", page, page, content, "hdr", 1.0)


def test_generator_sends_delimited_sources_and_image_and_parses_citations() -> None:
    client, seen = make_client(chat_handler("Altimeters measure height [2]."))
    gen = OpenRouterGenerator(client, "m", 100)
    passages = [_passage(101, "first text"), _passage(102, "second text")]
    answer = gen.generate("what?", passages, {102: PNG})
    assert answer.cited_chunk_ids == (102,)
    sent = body(seen[0])
    assert sent["max_tokens"] == 100
    assert sent["provider"] == PRIVACY_PROVIDER
    assert sent["messages"][0]["role"] == "system"
    parts = sent["messages"][1]["content"]
    texts = [p["text"] for p in parts if p["type"] == "text"]
    assert texts[0].startswith('<source n="1"')
    assert texts[1].startswith('<source n="2"')
    # the image sits right after source 2's block
    assert [p["type"] for p in parts] == ["text", "text", "image_url", "text"]


def test_generator_drops_invalid_markers() -> None:
    client, _ = make_client(chat_handler("Yes [1][9]. Also [0] and [3]."))
    gen = OpenRouterGenerator(client, "m", 100)
    answer = gen.generate("q", [_passage(7, "a"), _passage(8, "b")], {})
    assert answer.cited_chunk_ids == (7,)


def test_generator_with_no_passages_does_not_call_the_api() -> None:
    client, seen = make_client(chat_handler("should not be used"))
    answer = OpenRouterGenerator(client, "m", 100).generate("q", [], {})
    assert answer.text == IDK
    assert answer.cited_chunk_ids == ()
    assert seen == []
