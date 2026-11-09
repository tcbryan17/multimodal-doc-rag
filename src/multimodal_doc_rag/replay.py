"""Helpers for recording `replay/sample-run.json` (build-plan step 16).

The portfolio site replays a saved `/ask` response from a static host with NO backend, so the
relative figure URLs the API returns (`/figures/{id}.png`) would 404 there. We inline each
figure into the file as a base64 `data:` URI instead.
"""

import base64
import re
from collections.abc import Mapping, Sequence
from typing import Any

from multimodal_doc_rag.contracts import AskResponse

_FIGURE_URL = re.compile(r"^/figures/(\d+)\.png$")


def figure_chunk_ids(response: AskResponse) -> list[int]:
    """Chunk ids behind the response's `/figures/{id}.png` URLs, in citation order."""
    ids = []
    for citation in response.citations:
        match = _FIGURE_URL.match(citation.image_url or "")
        if match is not None:
            ids.append(int(match.group(1)))
    return ids


def inline_figures(response: AskResponse, pngs: Mapping[int, bytes]) -> AskResponse:
    """A copy of the response whose figure image URLs are data URIs. Other citations are
    untouched; a figure whose PNG is missing raises (a replay with a broken image is worse than
    no replay)."""
    citations = []
    for citation in response.citations:
        match = _FIGURE_URL.match(citation.image_url or "")
        if match is None:
            citations.append(citation)
            continue
        chunk_id = int(match.group(1))
        if chunk_id not in pngs:
            raise KeyError(f"no PNG for figure chunk {chunk_id} ({citation.image_url})")
        b64 = base64.b64encode(pngs[chunk_id]).decode("ascii")
        citations.append(citation.model_copy(update={"image_url": f"data:image/png;base64,{b64}"}))
    return response.model_copy(update={"citations": citations})


# How each trace step reads in the portfolio site's replay player.
_STEP_TEXT = {
    "retrieve": ("retriever", "Hybrid search (vector + keyword, fused with RRF): {detail}"),
    "rerank": ("reranker", "Cross-encoder rerank: {detail}"),
    "figures": ("figures", "Figure images sent to the model: {detail}"),
}
_USER_PAUSE_MS = 400  # a beat after the question appears, before the pipeline "starts"
_SOURCE_GAP_MS = 350  # between the answer and each source card


def decode_data_uri(uri: str) -> bytes:
    """The PNG bytes inside a `data:image/png;base64,...` URI."""
    head, _, data = uri.partition(",")
    if head != "data:image/png;base64" or not data:
        raise ValueError(f"not a base64 PNG data URI: {uri[:40]!r}")
    return base64.b64decode(data, validate=True)


def site_events(
    question: str, response: AskResponse, image_srcs: Sequence[str | None]
) -> list[dict[str, Any]]:
    """The recorded run as the portfolio site's replay events: `{t, who, text, image?}`.

    Timings are the run's own: each trace step appears after its measured `ms`, so the
    replay plays at the speed the real pipeline ran. `image_srcs[i]` is where the site serves
    citation i's figure (None for a text citation).
    """
    if len(image_srcs) != len(response.citations):
        raise ValueError("need one image_srcs entry per citation")
    events: list[dict[str, Any]] = [{"t": 0, "who": "user", "text": question}]
    t = _USER_PAUSE_MS
    for step in response.trace:
        t += step.ms
        if step.step == "generate":
            events.append({"t": t, "who": "assistant", "text": response.answer})
        elif step.step == "figures" and step.detail.startswith("0 "):
            continue  # no figures retrieved: nothing worth showing
        else:
            who, template = _STEP_TEXT.get(step.step, (step.step, "{detail}"))
            events.append({"t": t, "who": who, "text": template.format(detail=step.detail)})
    for n, (citation, src) in enumerate(zip(response.citations, image_srcs, strict=True), 1):
        t += _SOURCE_GAP_MS
        pages = citation.page + (f"–{citation.page_end}" if citation.page_end else "")
        event: dict[str, Any] = {
            "t": t,
            "who": "source",
            "text": f"[{n}] {citation.doc}, p. {pages}",
        }
        if src is not None:
            event["image"] = src
        events.append(event)
    return events
