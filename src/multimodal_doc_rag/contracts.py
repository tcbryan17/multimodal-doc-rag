"""Pydantic models for the `/ask` contract (ADR 0005) and the pipeline seam.

Optional response fields are omitted from the JSON when unset (the route uses
`response_model_exclude_none=True`), so a client sees `page_end`/`image_url`
either present with a value or absent, never `null`. This matches the
`"field"?: type` notation in the README contract.
"""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

MAX_QUESTION_LENGTH = 1000  # input limit, also a cost/abuse guard for the live demo


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    corpus: str | None = None
    doc: str | None = None


class Citation(BaseModel):
    doc: str
    page: str  # printed page label, e.g. "4-12"
    page_end: str | None = None
    snippet: str
    image_url: str | None = None


class TraceStep(BaseModel):
    step: str
    detail: str
    ms: int = Field(ge=0)


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    trace: list[TraceStep]


class Pipeline(Protocol):
    """Anything that can answer a question. The API depends only on this."""

    def ask(self, request: AskRequest) -> AskResponse: ...
