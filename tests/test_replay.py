"""inline_figures: figure citations become data URIs; everything else is left alone."""

import base64
import json

import pytest

from multimodal_doc_rag.contracts import AskResponse, Citation
from multimodal_doc_rag.replay import figure_chunk_ids, inline_figures


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
