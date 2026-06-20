from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.generated_name import Language
from app.models.semantic import Lexeme, Sense, SenseEmbedding
from app.services.embedding_provider import DEFAULT_EMBEDDING_MODEL, embed_query


MatchType = Literal["selected", "expanded"]


@dataclass(frozen=True)
class SenseSearchHit:
    sense: Sense
    match_type: MatchType
    score: float
    reason: str


def build_query_text_from_selected_senses(
    senses: list[Sense],
) -> str:
    parts: list[str] = []

    for sense in senses:
        lexeme = sense.lexeme
        language = lexeme.language

        parts.append(
            "\n".join(
                [
                    f"word: {lexeme.lemma}",
                    f"language: {language.name}",
                    f"part of speech: {lexeme.part_of_speech}",
                    f"definition: {sense.definition}",
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
) -> list[SenseSearchHit]:
    selected_senses = get_selected_senses(
        db,
        sense_ids=selected_sense_ids,
    )

    selected_hits = [
        SenseSearchHit(
            sense=sense,
            match_type="selected",
            score=1.0,
            reason="user_selected_meaning",
        )
        for sense in selected_senses
    ]

    if expansion_count <= 0 or not selected_senses:
        return selected_hits

    query_text = build_query_text_from_selected_senses(selected_senses)
    query_vector = embed_query(query_text)

    selected_ids = {sense.id for sense in selected_senses}

    distance = SenseEmbedding.embedding.cosine_distance(query_vector)

    statement = (
        select(SenseEmbedding, distance.label("distance"))
        .join(Sense, Sense.id == SenseEmbedding.sense_id)
        .join(Lexeme, Lexeme.id == Sense.lexeme_id)
        .join(Language, Language.id == Lexeme.language_id)
        .options(
            selectinload(SenseEmbedding.sense).selectinload(Sense.lexeme)
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
        statement.order_by(distance).limit(expansion_count)
    ).all()

    expanded_hits: list[SenseSearchHit] = []

    for embedding, raw_distance in rows:
        distance_value = float(raw_distance)
        score = max(0.0, 1.0 - distance_value)

        expanded_hits.append(
            SenseSearchHit(
                sense=embedding.sense,
                match_type="expanded",
                score=score,
                reason="pgvector_multilingual_e5_similarity",
            )
        )

    return [*selected_hits, *expanded_hits]