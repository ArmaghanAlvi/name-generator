from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.semantic import Sense
from app.services.sense_selection import (
    SenseSearchKey,
    sense_search_key_for_sense,
)
from app.utils.text import normalize_text


POPULAR_SENSE_BONUS = 0.025

GENERIC_PREFIXES = (
    "a source of ",
    "a kind of ",
    "a type of ",
    "a form of ",
    "a state of ",
    "a quality of ",
    "the quality of ",
    "a person who ",
    "someone who ",
    "something that ",
    "a thing that ",
    "a place where ",
    "the act of ",
    "the process of ",
)

BROAD_DOMAIN_TERMS = {
    "organ",
    "eye",
    "vision",
    "visual",
    "sight",
    "perception",
    "retina",
    "color",
    "colour",
    "camera",
    "photograph",
    "picture",
    "image",
    "object",
    "device",
    "instrument",
    "tool",
    "machine",
    "glass",
    "lens",
    "skin",
    "exposure",
    "wine",
    "island",
    "electricity",
    "electrical",
    "discharge",
    "cloud",
}

BROAD_DOMAIN_PHRASES = (
    "produced by",
    "resulting from",
    "exposure to",
    "made of",
    "passes through",
)

STOPWORDS = {
    "a",
    "an",
    "the",
    "of",
    "to",
    "in",
    "on",
    "for",
    "from",
    "by",
    "with",
    "and",
    "or",
    "as",
    "at",
    "is",
    "are",
    "was",
    "were",
    "be",
    "being",
    "been",
}


@dataclass(frozen=True)
class RerankCandidate:
    sense: Sense
    vector_score: float


@dataclass(frozen=True)
class RerankResult:
    sense: Sense
    vector_score: float
    final_score: float
    explanation_parts: tuple[str, ...]


def normalize_for_matching(text: str) -> str:
    return normalize_text(text).casefold()


def tokenize(text: str) -> set[str]:
    normalized = normalize_for_matching(text)
    tokens = set(re.findall(r"[a-z][a-z'-]{2,}", normalized))

    return {
        token
        for token in tokens
        if token not in STOPWORDS
    }


def generic_definition_penalty(
    candidate: Sense,
) -> tuple[float, str | None]:
    definition = normalize_for_matching(candidate.definition).strip()

    if not definition:
        return -0.08, "missing definition"

    if definition.startswith(GENERIC_PREFIXES):
        return -0.055, "generic definition pattern"

    if len(tokenize(definition)) <= 2:
        return -0.04, "very short/vague definition"

    return 0.0, None


def broad_domain_penalty(
    candidate: Sense,
) -> tuple[float, str | None]:
    definition = normalize_for_matching(candidate.definition)
    terms = tokenize(definition)

    matched_terms = sorted(terms & BROAD_DOMAIN_TERMS)
    matched_phrases = [
        phrase
        for phrase in BROAD_DOMAIN_PHRASES
        if phrase in definition
    ]

    if not matched_terms and not matched_phrases:
        return 0.0, None

    labels = matched_terms[:4] + matched_phrases[:2]

    return -0.05, f"broad-domain signal: {', '.join(labels)}"


def popular_sense_keys_in_candidate_set(
    *,
    candidates: list[RerankCandidate],
    sense_selection_counts: dict[SenseSearchKey, int] | None,
) -> set[SenseSearchKey]:
    """
    Within the current candidate set, find the upper 50% of exact meanings
    by selection/search count.

    Only meanings with selection_count > 0 are eligible.
    The bonus is constant, not proportional to count.
    """
    if not sense_selection_counts:
        return set()

    unique_keys: set[SenseSearchKey] = {
        sense_search_key_for_sense(candidate.sense)
        for candidate in candidates
    }

    scored_keys = [
        (
            key,
            sense_selection_counts.get(key, 0),
        )
        for key in unique_keys
    ]

    # Zero-search meanings never get the popularity bonus.
    scored_keys = [
        (key, count)
        for key, count in scored_keys
        if count > 0
    ]

    if not scored_keys:
        return set()

    scored_keys.sort(
        key=lambda item: item[1],
        reverse=True,
    )

    keep_count = max(1, (len(scored_keys) + 1) // 2)

    return {
        key
        for key, _count in scored_keys[:keep_count]
    }


def sense_popularity_bonus(
    *,
    candidate: Sense,
    popular_sense_keys: set[SenseSearchKey],
) -> tuple[float, str | None]:
    key = sense_search_key_for_sense(candidate)

    if key not in popular_sense_keys:
        return 0.0, None

    return POPULAR_SENSE_BONUS, "upper-half exact-meaning popularity"


def rerank_candidates(
    *,
    candidates: list[RerankCandidate],
    sense_selection_counts: dict[SenseSearchKey, int] | None = None,
) -> list[RerankResult]:
    popular_sense_keys = popular_sense_keys_in_candidate_set(
        candidates=candidates,
        sense_selection_counts=sense_selection_counts,
    )

    results: list[RerankResult] = []

    for candidate in candidates:
        score = candidate.vector_score
        explanation_parts: list[str] = [
            f"vector={candidate.vector_score:.3f}",
        ]

        adjustments = [
            sense_popularity_bonus(
                candidate=candidate.sense,
                popular_sense_keys=popular_sense_keys,
            ),
            generic_definition_penalty(candidate.sense),
            broad_domain_penalty(candidate.sense),
        ]

        for adjustment, reason in adjustments:
            score += adjustment

            if reason is not None and adjustment != 0:
                sign = "+" if adjustment > 0 else ""
                explanation_parts.append(f"{sign}{adjustment:.3f} {reason}")

        results.append(
            RerankResult(
                sense=candidate.sense,
                vector_score=candidate.vector_score,
                final_score=score,
                explanation_parts=tuple(explanation_parts),
            )
        )

    return sorted(
        results,
        key=lambda result: result.final_score,
        reverse=True,
    )