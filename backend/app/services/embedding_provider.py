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


# Sized for one 21-language width-3/depth-3 search (~290 distinct query texts)
# plus headroom, so a single search never evicts its own entries. ~25KB per
# entry as a Python float tuple => ~13MB at full occupancy.
_QUERY_CACHE_SIZE = 512


@lru_cache(maxsize=_QUERY_CACHE_SIZE)
def _embed_query_cached(text: str) -> tuple[float, ...]:
    """Cached core. Returns a TUPLE, not a list, so a caller that mutated the
    result could not poison the cache for every subsequent caller."""
    model = get_model()
    vector = model.encode(
        f"query: {text}",
        normalize_embeddings=True,
    )
    return tuple(float(value) for value in vector)


def embed_query(text: str) -> list[float]:
    """
    Use for user searches or selected-sense search queries.

    LRU-cached (roadmap C4a). Inference is deterministic for a fixed input and
    shape, so a cache hit returns the identical vector the model would have
    recomputed -- byte-identical by construction, and if anything it REMOVES a
    source of run-to-run variation.

    WHAT IT ACTUALLY SAVES, measured rather than assumed: within one search the
    only guaranteed duplicate is multi_hop_expansion._build_origin_query_vector
    vs the root expand() call -- they embed the same string
    (build_query_text_from_selected_senses([root_sense])) once per tree, so
    ~21 of ~290. Every other node has a distinct query text. The large win is
    ACROSS searches, and inside the eval harness, where capture_engine_reference
    re-embeds the same texts across 160 grid cells.

    The list() copy costs ~10us against a ~30ms inference.
    """
    return list(_embed_query_cached(text))