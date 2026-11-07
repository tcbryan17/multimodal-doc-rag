"""Vector helpers for embeddings."""

import math


def truncate_and_normalize(vec: list[float], dim: int) -> list[float]:
    """Keep the first `dim` values of `vec` and scale them to unit L2 length.

    Matryoshka-trained models (e.g. Qwen3 embeddings) pack the most important information
    into the leading dimensions, so dropping the tail loses little quality. The truncated
    vector is no longer unit length though, and cosine similarity (and pgvector's cosine
    distance) assumes unit vectors, so we re-normalise.
    """
    if dim <= 0:
        raise ValueError(f"dim must be positive, got {dim}")
    if dim > len(vec):
        raise ValueError(f"cannot truncate a {len(vec)}-dim vector to {dim} dims")
    head = vec[:dim]
    norm = math.sqrt(sum(x * x for x in head))
    if norm == 0.0:
        raise ValueError("cannot normalise a zero vector")
    return [x / norm for x in head]
