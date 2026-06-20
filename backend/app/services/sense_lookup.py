from __future__ import annotations

from sqlalchemy import asc, desc, func, nullslast, select
from sqlalchemy.orm import Session

from app.models.generated_name import Language
from app.models.semantic import (
    Lexeme,
    Sense,
    SenseAdminOverride,
    SenseSelectionStat,
)
from app.schemas.senses import SenseOptionResponse
from app.utils.text import normalize_text


def effective_definition(
    sense: Sense,
    override: SenseAdminOverride | None,
) -> str:
    if override and override.definition_override:
        return override.definition_override

    return sense.definition


def lookup_sense_options(
    db: Session,
    *,
    query: str,
    language_code: str | None = None,
    include_hidden: bool = False,
    limit: int = 50,
) -> list[SenseOptionResponse]:
    normalized_query = normalize_text(query)

    statement = (
        select(
            Sense,
            Lexeme,
            Language,
            SenseSelectionStat,
            SenseAdminOverride,
        )
        .join(Lexeme, Lexeme.id == Sense.lexeme_id)
        .join(Language, Language.id == Lexeme.language_id)
        .outerjoin(
            SenseSelectionStat,
            SenseSelectionStat.sense_id == Sense.id,
        )
        .outerjoin(
            SenseAdminOverride,
            SenseAdminOverride.sense_id == Sense.id,
        )
        .where(Lexeme.normalized_lemma == normalized_query)
    )

    if language_code is not None:
        statement = statement.where(Language.code == language_code)

    if not include_hidden:
        statement = statement.where(
            Sense.visibility_status == "visible",
            (SenseAdminOverride.is_hidden.is_(None))
            | (SenseAdminOverride.is_hidden.is_(False)),
        )

    statement = (
        statement.order_by(
            nullslast(asc(SenseAdminOverride.pinned_rank)),
            desc(func.coalesce(SenseSelectionStat.selection_count, 0)),
            asc(Sense.source_order),
            asc(Sense.sense_index),
        )
        .limit(limit)
    )

    rows = db.execute(statement).all()

    options: list[SenseOptionResponse] = []

    for sense, lexeme, language, stat, override in rows:
        selection_count = (
            stat.selection_count
            if stat is not None
            else 0
        )

        is_hidden = (
            sense.visibility_status == "hidden"
            or bool(override and override.is_hidden)
        )

        options.append(
            SenseOptionResponse(
                senseId=sense.id,
                word=override.label_override
                if override and override.label_override
                else lexeme.lemma,
                language=language.name,
                languageCode=language.code,
                partOfSpeech=lexeme.part_of_speech,
                definition=effective_definition(sense, override),
                rawGlosses=sense.raw_glosses,
                tags=sense.raw_tags,
                categories=sense.categories,
                selectionCount=selection_count,
                pinnedRank=override.pinned_rank if override else None,
                isHidden=is_hidden,
                sourceLocator=sense.source_locator,
            )
        )

    return options