from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.semantic import Sense
from app.utils.text import normalize_text
from app.services.word_search_stats import WordSearchKey, word_search_key_for_sense

POPULAR_WORD_BONUS = 0.025

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
    "thing",
    "something",
    "someone",
    "person",
    "people",
    "place",
    "state",
    "quality",
    "act",
    "action",
    "process",
    "condition",
    "kind",
    "type",
    "form",
    "way",
    "source",
    "supply",
    "used",
    "having",
    "related",
    "pertaining",
}

GENERIC_PREFIXES = (
    "a source of ",
    "an source of ",
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

DOMAIN_ONLY_WORDS = {
    "eye",
    "organ",
    "color",
    "colour",
    "vision",
    "visual",
    "sight",
    "perception",
    "camera",
    "picture",
    "photograph",
    "image",
    "object",
    "scene",
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


def tokenize(text: str) -> set[str]:
    normalized = normalize_text(text).casefold()
    tokens = set(re.findall(r"[a-z][a-z'-]{2,}", normalized))

    return {
        token
        for token in tokens
        if token not in STOPWORDS
    }


def sense_text(sense: Sense) -> str:
    lexeme = sense.lexeme

    return " ".join(
        [
            lexeme.lemma,
            lexeme.part_of_speech,
            sense.definition,
            " ".join(sense.raw_glosses),
            " ".join(sense.raw_tags),
            " ".join(sense.categories),
        ]
    )


def selected_text(selected_senses: list[Sense]) -> str:
    return " ".join(
        sense_text(sense)
        for sense in selected_senses
    )


def selected_anchor_terms(selected_senses: list[Sense]) -> set[str]:
    """
    Important terms from the user's selected meaning.

    For:
        light — A source of illumination

    this should keep:
        light, illumination

    and mostly ignore:
        source
    """
    text = selected_text(selected_senses)
    terms = tokenize(text)

    for sense in selected_senses:
        lemma = normalize_text(sense.lexeme.lemma).casefold()

        if lemma and lemma not in STOPWORDS:
            terms.add(lemma)

    return terms


def lexical_overlap_bonus(
    *,
    selected_terms: set[str],
    candidate: Sense,
) -> tuple[float, str | None]:
    candidate_terms = tokenize(sense_text(candidate))

    if not selected_terms or not candidate_terms:
        return 0.0, None

    overlap = selected_terms & candidate_terms

    if not overlap:
        return -0.025, "no important-term overlap"

    ratio = len(overlap) / max(len(selected_terms), 1)

    if ratio >= 0.35:
        return 0.07, f"strong term overlap: {', '.join(sorted(overlap)[:5])}"

    if ratio >= 0.15:
        return 0.04, f"some term overlap: {', '.join(sorted(overlap)[:5])}"

    return 0.015, f"weak term overlap: {', '.join(sorted(overlap)[:5])}"


def selected_lemma_bonus(
    *,
    selected_senses: list[Sense],
    candidate: Sense,
) -> tuple[float, str | None]:
    candidate_text = normalize_text(sense_text(candidate)).casefold()

    selected_lemmas = {
        normalize_text(sense.lexeme.lemma).casefold()
        for sense in selected_senses
    }

    for lemma in selected_lemmas:
        if len(lemma) >= 3 and lemma in candidate_text:
            return 0.05, f"candidate text mentions selected word: {lemma}"

    return 0.0, None


def part_of_speech_bonus(
    *,
    selected_senses: list[Sense],
    candidate: Sense,
) -> tuple[float, str | None]:
    selected_pos = {
        sense.lexeme.part_of_speech.casefold()
        for sense in selected_senses
    }

    candidate_pos = candidate.lexeme.part_of_speech.casefold()

    if candidate_pos in selected_pos:
        return 0.025, "same part of speech"

    # Noun/adjective/verb are often all useful for name generation,
    # so do not punish heavily.
    flexible_pos = {"noun", "verb", "adj", "adjective"}

    if candidate_pos in flexible_pos and selected_pos & flexible_pos:
        return 0.01, "compatible part of speech"

    return -0.015, "less compatible part of speech"


def generic_definition_penalty(
    candidate: Sense,
) -> tuple[float, str | None]:
    definition = normalize_text(candidate.definition).casefold().strip()

    if not definition:
        return -0.08, "missing definition"

    if definition.startswith(GENERIC_PREFIXES):
        return -0.055, "generic definition pattern"

    if len(tokenize(definition)) <= 2:
        return -0.04, "very short/vague definition"

    return 0.0, None


def generic_template_mismatch_penalty(
    *,
    selected_senses: list[Sense],
    candidate: Sense,
) -> tuple[float, str | None]:
    """
    Handles cases like:

        light — A source of illumination
        well  — A source of supply

    These are structurally similar, but the important complement differs.
    """
    selected_defs = [
        normalize_text(sense.definition).casefold().strip()
        for sense in selected_senses
    ]

    candidate_def = normalize_text(candidate.definition).casefold().strip()

    for prefix in GENERIC_PREFIXES:
        selected_has_prefix = any(
            definition.startswith(prefix)
            for definition in selected_defs
        )

        candidate_has_prefix = candidate_def.startswith(prefix)

        if selected_has_prefix and candidate_has_prefix:
            selected_terms = selected_anchor_terms(selected_senses)
            candidate_terms = tokenize(candidate_def)
            overlap = selected_terms & candidate_terms

            if not overlap:
                return -0.09, "same generic template but different key terms"

    return 0.0, None


def broad_domain_penalty(
    *,
    selected_terms: set[str],
    candidate: Sense,
) -> tuple[float, str | None]:
    """
    Penalizes terms that are merely in the broad domain but not close
    lexical alternatives.

    This is still generic. It is not specifically "light".
    """
    candidate_terms = tokenize(sense_text(candidate))

    domain_overlap = candidate_terms & DOMAIN_ONLY_WORDS
    important_overlap = candidate_terms & selected_terms

    if domain_overlap and not important_overlap:
        return -0.06, f"broad domain-only terms: {', '.join(sorted(domain_overlap)[:5])}"

    return 0.0, None


def source_order_bonus(candidate: Sense) -> tuple[float, str | None]:
    """
    Earlier senses in Kaikki/Wiktionary order tend to be more central.
    Small nudge only.
    """
    if candidate.sense_index <= 2:
        return 0.015, "early source sense"

    return 0.0, None


def popular_word_keys_in_candidate_set(
    *,
    candidates: list[RerankCandidate],
    word_search_counts: dict[WordSearchKey, int] | None,
) -> set[WordSearchKey]:
    """
    Within the current candidate set, find the upper 50% of words by
    search count.

    Only words with search_count > 0 are eligible.

    The bonus is constant, not proportional to count.
    """

    if not word_search_counts:
        return set()

    unique_keys: set[WordSearchKey] = {
        word_search_key_for_sense(candidate.sense)
        for candidate in candidates
    }

    scored_keys = [
        (
            key,
            word_search_counts.get(key, 0),
        )
        for key in unique_keys
    ]

    # Critical rule:
    # zero-search words never get the popularity bonus.
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


def word_popularity_bonus(
    *,
    candidate: Sense,
    popular_word_keys: set[WordSearchKey],
) -> tuple[float, str | None]:
    key = word_search_key_for_sense(candidate)

    if key not in popular_word_keys:
        return 0.0, None

    return POPULAR_WORD_BONUS, "upper-half word search popularity"


def rerank_candidates(
    *,
    selected_senses: list[Sense],
    candidates: list[RerankCandidate],
    word_search_counts: dict[WordSearchKey, int] | None = None,
) -> list[RerankResult]:
    selected_terms = selected_anchor_terms(selected_senses)

    popular_word_keys = popular_word_keys_in_candidate_set(
        candidates=candidates,
        word_search_counts=word_search_counts,
    )

    results: list[RerankResult] = []

    for candidate in candidates:
        score = candidate.vector_score
        explanation_parts: list[str] = [
            f"vector={candidate.vector_score:.3f}",
        ]

        adjustments = [
            lexical_overlap_bonus(
                selected_terms=selected_terms,
                candidate=candidate.sense,
            ),
            selected_lemma_bonus(
                selected_senses=selected_senses,
                candidate=candidate.sense,
            ),
            part_of_speech_bonus(
                selected_senses=selected_senses,
                candidate=candidate.sense,
            ),
            word_popularity_bonus(
                candidate=candidate.sense,
                popular_word_keys=popular_word_keys,
            ),
            generic_definition_penalty(candidate.sense),
            generic_template_mismatch_penalty(
                selected_senses=selected_senses,
                candidate=candidate.sense,
            ),
            broad_domain_penalty(
                selected_terms=selected_terms,
                candidate=candidate.sense,
            ),
            source_order_bonus(candidate.sense),
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