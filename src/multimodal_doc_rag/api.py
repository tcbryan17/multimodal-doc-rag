"""HTTP API. `/ask` (see README contract) gets added once the pipeline exists."""

from fastapi import FastAPI

app = FastAPI(title="multimodal-doc-rag")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
