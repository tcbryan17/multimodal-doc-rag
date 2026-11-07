import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from multimodal_doc_rag.api import app, get_pipeline
from multimodal_doc_rag.contracts import (
    AskRequest,
    AskResponse,
    Citation,
    TraceStep,
)

REPLAY = Path(__file__).resolve().parents[1] / "replay" / "sample-run.json"


class FakePipeline:
    def __init__(self, response: AskResponse) -> None:
        self.response = response
        self.requests: list[AskRequest] = []

    def ask(self, request: AskRequest) -> AskResponse:
        self.requests.append(request)
        return self.response


def _response(*citations: Citation) -> AskResponse:
    return AskResponse(
        answer="42",
        citations=list(citations),
        trace=[TraceStep(step="retrieve", detail="top 3", ms=12)],
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def _inject(response: AskResponse) -> FakePipeline:
    fake = FakePipeline(response)
    app.dependency_overrides[get_pipeline] = lambda: fake
    return fake


def test_exact_shape_optional_fields_absent(client: TestClient) -> None:
    _inject(_response(Citation(doc="faa", page="4-12", snippet="s")))
    r = client.post("/ask", json={"question": "hi"})
    assert r.status_code == 200
    assert r.json() == {
        "answer": "42",
        "citations": [{"doc": "faa", "page": "4-12", "snippet": "s"}],
        "trace": [{"step": "retrieve", "detail": "top 3", "ms": 12}],
    }


def test_optional_fields_present_when_set(client: TestClient) -> None:
    cite = Citation(
        doc="faa",
        page="4-12",
        page_end="4-13",
        snippet="s",
        image_url="data:image/png;base64,AA",
    )
    _inject(_response(cite))
    body = client.post("/ask", json={"question": "hi"}).json()
    assert body["citations"][0] == {
        "doc": "faa",
        "page": "4-12",
        "page_end": "4-13",
        "snippet": "s",
        "image_url": "data:image/png;base64,AA",
    }


def test_negative_ms_rejected() -> None:
    with pytest.raises(ValueError):
        TraceStep(step="x", detail="y", ms=-1)


def test_zero_ms_allowed() -> None:
    assert TraceStep(step="x", detail="y", ms=0).ms == 0


def test_question_is_stripped(client: TestClient) -> None:
    fake = _inject(_response())
    client.post("/ask", json={"question": "  hello  "})
    assert fake.requests[0].question == "hello"


@pytest.mark.parametrize("question", ["", "   ", "x" * 1001])
def test_bad_question_returns_422(client: TestClient, question: str) -> None:
    _inject(_response())
    assert client.post("/ask", json={"question": question}).status_code == 422


def test_max_length_question_accepted(client: TestClient) -> None:
    _inject(_response())
    assert client.post("/ask", json={"question": "x" * 1000}).status_code == 200


def test_unknown_field_returns_422(client: TestClient) -> None:
    _inject(_response())
    r = client.post("/ask", json={"question": "hi", "extra": 1})
    assert r.status_code == 422


def test_missing_question_returns_422(client: TestClient) -> None:
    _inject(_response())
    assert client.post("/ask", json={}).status_code == 422


def test_no_pipeline_returns_503(client: TestClient) -> None:
    r = client.post("/ask", json={"question": "hi"})
    assert r.status_code == 503
    assert "pipeline not configured" in r.json()["detail"]


def test_filters_passed_through(client: TestClient) -> None:
    fake = _inject(_response())
    client.post("/ask", json={"question": "q", "corpus": "faa", "doc": "phak"})
    assert fake.requests[0].corpus == "faa"
    assert fake.requests[0].doc == "phak"


def test_filters_default_to_none(client: TestClient) -> None:
    fake = _inject(_response())
    client.post("/ask", json={"question": "q"})
    assert fake.requests[0].corpus is None
    assert fake.requests[0].doc is None


def test_replay_file_matches_contract() -> None:
    if not REPLAY.exists():
        pytest.skip("replay/sample-run.json not created yet (build-plan step 16)")
    AskResponse.model_validate(json.loads(REPLAY.read_text()))
