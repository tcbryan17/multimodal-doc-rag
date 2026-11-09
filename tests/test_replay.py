"""inline_figures: figure citations become data URIs; everything else is left alone."""

import base64
import json

import pytest

from multimodal_doc_rag.contracts import AskResponse, Citation, TraceStep
from multimodal_doc_rag.replay import (
    decode_data_uri,
    figure_chunk_ids,
    inline_figures,
    site_events,
)


def response() -> AskResponse:
    return AskResponse(
        answer="a",
        citations=[
            Citation(doc="D", page="1", snippet="text"),
            Citation(doc="D", page="2", snippet="fig", image_url="/figures/7.png"),
            Citation(doc="D", page="3", snippet="x", image_url="https://elsewhere/figures/8.png"),
        ],
        trace=[],
    )


def test_figure_citations_become_data_uris_and_others_are_untouched() -> None:
    original = response()
    out = inline_figures(original, {7: b"\x89PNGbytes"})
    uri = out.citations[1].image_url
    assert uri is not None and uri.startswith("data:image/png;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]) == b"\x89PNGbytes"
    assert out.citations[0] == original.citations[0]
    assert out.citations[2] == original.citations[2]  # not a /figures/ path: left as is
    assert original.citations[1].image_url == "/figures/7.png"  # input not mutated


def test_missing_png_raises() -> None:
    with pytest.raises(KeyError, match="7"):
        inline_figures(response(), {})


def test_figure_chunk_ids_in_order() -> None:
    assert figure_chunk_ids(response()) == [7]


def test_output_validates_and_omits_none_fields() -> None:
    out = inline_figures(response(), {7: b"x"})
    data = json.loads(out.model_dump_json(indent=2, exclude_none=True))
    assert "page_end" not in data["citations"][0]
    AskResponse.model_validate(data)


def _traced() -> AskResponse:
    return AskResponse(
        answer="5.1 °C [1]",
        citations=[
            Citation(
                doc="Ch. 4", page="4-3", snippet="table", image_url="data:image/png;base64,eA=="
            ),
            Citation(doc="Ch. 9", page="9-2", page_end="9-3", snippet="text"),
        ],
        trace=[
            TraceStep(step="retrieve", detail="30 candidates", ms=500),
            TraceStep(step="rerank", detail="kept 5 of 30", ms=1000),
            TraceStep(step="figures", detail="1 images", ms=5),
            TraceStep(step="generate", detail="2 citations", ms=2000),
        ],
    )


def test_site_events_play_at_the_runs_own_speed() -> None:
    events = site_events("q?", _traced(), ["assets/replays/rag-1.png", None])
    assert [e["who"] for e in events] == [
        "user", "retriever", "reranker", "figures", "assistant", "source", "source",
    ]  # fmt: skip
    times = [e["t"] for e in events]
    assert times == sorted(times) and times[0] == 0
    assert times[2] - times[1] == 1000  # the rerank step's measured ms
    assert events[4]["text"] == "5.1 °C [1]"
    assert events[5]["text"] == "[1] Ch. 4, p. 4-3"
    assert events[5]["image"] == "assets/replays/rag-1.png"
    assert events[6]["text"] == "[2] Ch. 9, p. 9-2–9-3" and "image" not in events[6]


def test_site_events_skip_an_empty_figures_step_and_check_lengths() -> None:
    resp = _traced()
    resp.trace[2] = TraceStep(step="figures", detail="0 images", ms=1)
    assert "figures" not in [e["who"] for e in site_events("q", resp, [None, None])]
    with pytest.raises(ValueError, match="one image_srcs entry"):
        site_events("q", resp, [None])


def test_decode_data_uri() -> None:
    assert decode_data_uri("data:image/png;base64,eA==") == b"x"
    with pytest.raises(ValueError):
        decode_data_uri("/figures/7.png")
