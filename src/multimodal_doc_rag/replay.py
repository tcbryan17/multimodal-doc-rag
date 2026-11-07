"""Helpers for recording `replay/sample-run.json` (build-plan step 16).

The portfolio site replays a saved `/ask` response from a static host with NO backend, so the
relative figure URLs the API returns (`/figures/{id}.png`) would 404 there. We inline each
figure into the file as a base64 `data:` URI instead.
"""

import base64
import re
from collections.abc import Mapping

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
