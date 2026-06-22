from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.generated_name import Language
from app.models.semantic import Lexeme, Sense, SenseEmbedding
from app.services.embedding_provider import DEFAULT_EMBEDDING_MODEL, embed_query
from app.utils.text import normalize_text
from app.services.sense_selection import get_sense_selection_counts_for_senses
from app.services.sense_reranker import (
    RerankCandidate,
    rerank_candidates,
)

MatchType = Literal["selected", "expanded"]


@dataclass(frozen=True)
class SenseSearchHit:
    sense: Sense
    match_type: MatchType
    score: float
    reason: str


def display_word_key_for_sense(sense: Sense) -> str:
    """
    Determines whether two sense results count as the same displayed word.

    For now, this dedupes globally by displayed lemma:
        light/noun and light/adjective collapse to "light"

    Later, if you want to allow same spelling across different languages,
    change this to include language code.
    """
    return normalize_text(sense.lexeme.lemma)


def word_length_allowed(
    sense: Sense,
    *,
    min_length: int,
    max_length: int,
) -> bool:
    length = len(sense.lexeme.lemma)

    return min_length <= length <= max_length


def build_query_text_from_selected_senses(
    senses: list[Sense],
) -> str:
    parts: list[str] = [
        (
            "Find near-synonyms, lexical equivalents, translation-like equivalents, "
            "and poetic word alternatives for the selected meaning. "
            "Prefer candidates that mean nearly the same thing."
        )
    ]

    for sense in senses:
        lexeme = sense.lexeme
        language = lexeme.language

        extra_glosses = "; ".join(sense.raw_glosses[1:4])

        parts.append(
            "\n".join(
                [
                    f"target word: {lexeme.lemma}",
                    f"target meaning of {lexeme.lemma}: {sense.definition}",
                    f"definition: {sense.definition}",
                    f"additional glosses: {extra_glosses}",
                    f"part of speech: {lexeme.part_of_speech}",
                    f"language: {language.name}",
                ]
            )
        )

    return "\n\n".join(parts)


def get_selected_senses(
    db: Session,
    *,
    sense_ids: list[int],
) -> list[Sense]:
    if not sense_ids:
        return []

    return list(
        db.scalars(
            select(Sense)
            .options(
                selectinload(Sense.lexeme).selectinload(Lexeme.language)
            )
            .where(
                Sense.id.in_(sense_ids),
                Sense.visibility_status == "visible",
            )
        ).all()
    )


def expand_from_selected_senses(
    db: Session,
    *,
    selected_sense_ids: list[int],
    expansion_count: int,
    target_language: str | None = None,
    min_length: int = 0,
    max_length: int = 30,
) -> list[SenseSearchHit]:
    selected_senses = get_selected_senses(
        db,
        sense_ids=selected_sense_ids,
    )

    hits: list[SenseSearchHit] = []
    displayed_word_keys: set[str] = set()

    # 0th expansion:
    # Show the exact selected meaning, but only once per displayed word.
    for sense in selected_senses:
        if not word_length_allowed(
            sense,
            min_length=min_length,
            max_length=max_length,
        ):
            continue

        word_key = display_word_key_for_sense(sense)

        if word_key in displayed_word_keys:
            continue

        displayed_word_keys.add(word_key)

        hits.append(
            SenseSearchHit(
                sense=sense,
                match_type="selected",
                score=1.0,
                reason="user_selected_meaning",
            )
        )

    if expansion_count <= 0 or not selected_senses:
        return hits

    query_text = build_query_text_from_selected_senses(selected_senses)
    query_vector = embed_query(query_text)

    selected_ids = {
        sense.id
        for sense in selected_senses
    }

    distance = SenseEmbedding.embedding.cosine_distance(query_vector)

    # Important:
    # We fetch more than the requested expansion count because many nearby
    # vector hits may be duplicate senses of the same displayed word.
    candidate_fetch_limit = min(
        max(expansion_count * 50, 100),
        1000,
    )

    statement = (
        select(SenseEmbedding, distance.label("distance"))
        .join(Sense, Sense.id == SenseEmbedding.sense_id)
        .join(Lexeme, Lexeme.id == Sense.lexeme_id)
        .join(Language, Language.id == Lexeme.language_id)
        .options(
            selectinload(SenseEmbedding.sense)
            .selectinload(Sense.lexeme)
            .selectinload(Lexeme.language)
        )
        .where(
            SenseEmbedding.embedding_model == DEFAULT_EMBEDDING_MODEL,
            Sense.visibility_status == "visible",
            ~SenseEmbedding.sense_id.in_(selected_ids),
        )
    )

    if target_language is not None:
        statement = statement.where(Language.name == target_language)

    rows = db.execute(
        statement.order_by(distance).limit(candidate_fetch_limit)
    ).all()

    candidate_groups: dict[str, list[RerankCandidate]] = {}

    for embedding, raw_distance in rows:
        sense = embedding.sense

        if not word_length_allowed(
            sense,
            min_length=min_length,
            max_length=max_length,
        ):
            continue

        word_key = display_word_key_for_sense(sense)

        # The exact selected word is already shown as the 0th result.
        # Do not show another sense of the same displayed word as an expansion.
        if word_key in displayed_word_keys:
            continue

        distance_value = float(raw_distance)
        vector_score = max(0.0, 1.0 - distance_value)

        candidate_groups.setdefault(word_key, []).append(
            RerankCandidate(
                sense=sense,
                vector_score=vector_score,
            )
        )

    duplicate_candidates = [
        candidate
        for group in candidate_groups.values()
        for candidate in group
    ]

    duplicate_candidate_senses = [
        candidate.sense
        for candidate in duplicate_candidates
    ]

    sense_selection_counts = get_sense_selection_counts_for_senses(
        db,
        senses=duplicate_candidate_senses,
    )

    def duplicate_candidate_sort_key(
        candidate: RerankCandidate,
    ) -> tuple[int, float]:
        # If multiple candidate senses have the same displayed word, choose the
        # exact meaning that has been selected/searched most often.
        # If selection counts tie, keep the strongest vector match.
        return (
            sense_selection_counts.get(candidate.sense.id, 0),
            candidate.vector_score,
        )

    rerank_candidates_input = [
        max(group, key=duplicate_candidate_sort_key)
        for group in candidate_groups.values()
    ]

    reranked = rerank_candidates(
        candidates=rerank_candidates_input,
        sense_selection_counts=sense_selection_counts,
    )

    for result in reranked[:expansion_count]:
        hits.append(
            SenseSearchHit(
                sense=result.sense,
                match_type="expanded",
                score=result.final_score,
                reason=(
                    "pgvector_similarity_auto_reranked: "
                    + " | ".join(result.explanation_parts)
                ),
            )
        )

    return hits