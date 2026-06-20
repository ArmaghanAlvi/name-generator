from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer


DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
DEFAULT_EMBEDDING_DIMENSIONS = 768


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer(DEFAULT_EMBEDDING_MODEL)


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