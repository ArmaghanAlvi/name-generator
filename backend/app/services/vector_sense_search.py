from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.generated_name import Language
from app.models.semantic import Lexeme, Sense, SenseEmbedding
from app.services.embedding_provider import DEFAULT_EMBEDDING_MODEL, embed_query
from app.utils.text import normalize_text


MatchType = Literal["selected", "expanded"]


@dataclass(frozen=True)
class SenseSearchHit:
    sense: Sense
    match_type: MatchType
    score: float
    reason: str


GENERIC_DEFINITION_PREFIXES = (
    "a source of ",
    "an source of ",
    "a kind of ",
    "a type of ",
    "a person who ",
    "someone who ",
    "something that ",
    "a thing that ",
    "a place where ",
    "a state of ",
)


def generic_definition_penalty(definition: str) -> float:
    normalized = definition.strip().casefold()

    if normalized.startswith(GENERIC_DEFINITION_PREFIXES):
        return 0.08

    return 0.0


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
    parts: list[str] = []

    for sense in senses:
        lexeme = sense.lexeme
        language = lexeme.language

        extra_glosses = "; ".join(sense.raw_glosses[1:4])
        tags = ", ".join(sense.raw_tags[:12])

        parts.append(
            "\n".join(
                [
                    f"Find words semantically related to this meaning.",
                    f"target word: {lexeme.lemma}",
                    f"target meaning of {lexeme.lemma}: {sense.definition}",
                    f"definition: {sense.definition}",
                    f"additional glosses: {extra_glosses}",
                    f"part of speech: {lexeme.part_of_speech}",
                    f"language: {language.name}",
                    f"semantic tags: {tags}",
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

    expanded_count = 0

    MIN_EXPANSION_SCORE = 0.72

    for embedding, raw_distance in rows:
        sense = embedding.sense

        if not word_length_allowed(
            sense,
            min_length=min_length,
            max_length=max_length,
        ):
            continue

        word_key = display_word_key_for_sense(sense)

        if word_key in displayed_word_keys:
            continue

        distance_value = float(raw_distance)
        score = max(0.0, 1.0 - distance_value)
        score -= generic_definition_penalty(sense.definition)

        if score < MIN_EXPANSION_SCORE:
            continue

        displayed_word_keys.add(word_key)

        hits.append(
            SenseSearchHit(
                sense=sense,
                match_type="expanded",
                score=score,
                reason="pgvector_multilingual_e5_similarity",
            )
        )

        expanded_count += 1

        if expanded_count >= expansion_count:
            break

    return hits