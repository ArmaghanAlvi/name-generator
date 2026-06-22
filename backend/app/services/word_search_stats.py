from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.semantic import Lexeme, Sense, WordSearchEvent, WordSearchStat


WordSearchKey = tuple[int, str]


def word_search_key_for_sense(sense: Sense) -> WordSearchKey:
    return (
        sense.lexeme.language_id,
        sense.lexeme.normalized_lemma,
    )


def _record_word_search_key(
    db: Session,
    *,
    language_id: int,
    normalized_lemma: str,
    query_text: str,
) -> None:
    if not normalized_lemma:
        return

    stat = db.scalar(
        select(WordSearchStat).where(
            WordSearchStat.language_id == language_id,
            WordSearchStat.normalized_lemma == normalized_lemma,
        )
    )

    if stat is None:
        stat = WordSearchStat(
            language_id=language_id,
            normalized_lemma=normalized_lemma,
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
            normalized_query=normalized_lemma,
        )
    )


def record_word_search_for_senses(
    db: Session,
    *,
    senses: Iterable[Sense],
    query_text: str,
) -> None:
    """
    Record one word-level search per language + lemma.

    This deliberately ignores the exact meaning. If the user searches
    any meaning of English "light", that increments:

        (English language_id, "light")

    It also dedupes within one request, so selecting multiple senses of
    the same word does not count as multiple word searches.
    """
    seen_keys: set[WordSearchKey] = set()

    for sense in senses:
        key = word_search_key_for_sense(sense)

        if key in seen_keys:
            continue

        seen_keys.add(key)

        language_id, normalized_lemma = key

        _record_word_search_key(
            db,
            language_id=language_id,
            normalized_lemma=normalized_lemma,
            query_text=query_text,
        )


def record_word_search_for_sense_ids(
    db: Session,
    *,
    sense_ids: Iterable[int],
    query_text: str,
) -> None:
    unique_sense_ids = list(dict.fromkeys(sense_ids))

    if not unique_sense_ids:
        return

    senses = list(
        db.scalars(
            select(Sense)
            .options(
                selectinload(Sense.lexeme).selectinload(Lexeme.language)
            )
            .where(Sense.id.in_(unique_sense_ids))
        ).all()
    )

    record_word_search_for_senses(
        db,
        senses=senses,
        query_text=query_text,
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