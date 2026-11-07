"""HTTP API: `/health` and `/ask` (contract in README and ADR 0005)."""

from fastapi import Depends, FastAPI, HTTPException

from multimodal_doc_rag.contracts import AskRequest, AskResponse, Pipeline

app = FastAPI(title="multimodal-doc-rag")


def get_pipeline() -> Pipeline:
    """Dependency that supplies the pipeline to `/ask`.

    Dependency injection: the route does not build its own pipeline, it
    declares `Depends(get_pipeline)` and FastAPI calls this function per
    request. Tests replace it with a fake via `app.dependency_overrides`.
    In a later step (9) the real pipeline will itself receive its DB
    connection through a dependency, so end-to-end tests can hand it the
    test's own transaction-bound connection.
    """
    raise HTTPException(status_code=503, detail="pipeline not configured")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# exclude_none: optional fields (page_end, image_url) are absent, not null.
@app.post("/ask", response_model=AskResponse, response_model_exclude_none=True)
def ask(
    request: AskRequest,
    pipeline: Pipeline = Depends(get_pipeline),  # noqa: B008
) -> AskResponse:
    return pipeline.ask(request)
