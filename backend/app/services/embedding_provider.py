from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer

import torch

DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
DEFAULT_EMBEDDING_DIMENSIONS = 768


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    device = (
        "mps" if torch.backends.mps.is_available()
        else "cuda" if torch.cuda.is_available()
        else "cpu"
    )
    return SentenceTransformer(DEFAULT_EMBEDDING_MODEL, device=device)


def embed_passage(text: str) -> list[float]:
    """
    Use for stored sense definitions.
    E5 models are trained with query:/passage: prefixes.
    """
    model = get_model()
    vector = model.encode(
        f"passage: {text}",
        normalize_embeddings=True,
    )

    return [float(value) for value in vector]


def embed_passages(texts: list[str]) -> list[list[float]]:
    """Batch version of embed_passage for bulk backfill."""
    model = get_model()
    vectors = model.encode(
        [f"passage: {t}" for t in texts],
        normalize_embeddings=True,
        batch_size=64,
        show_progress_bar=False,
    )
    return [[float(v) for v in row] for row in vectors]


def embed_query(text: str) -> list[float]:
    """
    Use for user searches or selected-sense search queries.
    """
    model = get_model()
    vector = model.encode(
        f"query: {text}",
        normalize_embeddings=True,
    )

    return [float(value) for value in vector]