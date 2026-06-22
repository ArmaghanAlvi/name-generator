from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.generated_name import Language
from app.models.semantic import Sense, WordSearchEvent, WordSearchStat
from app.utils.text import normalize_text


WordSearchKey = tuple[int | None, str]


def record_word_search(
    db: Session,
    *,
    query_text: str,
    language_code: str | None,
) -> None:
    normalized = normalize_text(query_text)

    if not normalized:
        return

    language_id: int | None = None

    if language_code is not None:
        language = db.scalar(
            select(Language).where(Language.code == language_code)
        )
        language_id = language.id if language is not None else None

    stat = db.scalar(
        select(WordSearchStat).where(
            WordSearchStat.language_id == language_id,
            WordSearchStat.normalized_lemma == normalized,
        )
    )

    if stat is None:
        stat = WordSearchStat(
            language_id=language_id,
            normalized_lemma=normalized,
            search_count=0,
        )
        db.add(stat)
        db.flush()

    stat.search_count += 1
    stat.last_searched_at = datetime.now(UTC)

    db.add(
        WordSearchEvent(
            language_id=language_id,
            query_text=query_text,
            normalized_query=normalized,
        )
    )


def word_search_key_for_sense(sense: Sense) -> WordSearchKey:
    return (
        sense.lexeme.language_id,
        sense.lexeme.normalized_lemma,
    )


def get_word_search_counts_for_senses(
    db: Session,
    *,
    senses: Iterable[Sense],
) -> dict[WordSearchKey, int]:
    keys = {
        word_search_key_for_sense(sense)
        for sense in senses
    }

    if not keys:
        return {}

    language_ids = {
        language_id
        for language_id, _normalized_lemma in keys
    }

    lemmas = {
        normalized_lemma
        for _language_id, normalized_lemma in keys
    }

    rows = db.scalars(
        select(WordSearchStat).where(
            WordSearchStat.language_id.in_(language_ids),
            WordSearchStat.normalized_lemma.in_(lemmas),
        )
    ).all()

    counts: dict[WordSearchKey, int] = {}

    for row in rows:
        key = (
            row.language_id,
            row.normalized_lemma,
        )

        if key in keys:
            counts[key] = row.search_count

    return counts