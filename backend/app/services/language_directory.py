"""
The imported-language directory -- one query SHAPE per language, one cache,
three consumers.

WHY A LOOP, NOT ONE COMBINED QUERY (Phase C, Step 0 diagnostic): a single
GROUP BY or EXISTS statement asking about all 21 languages at once gives the
planner room to hash-join full scans of senses/lexemes instead of using
ix_lexemes_language_pos + ix_senses_lexeme_id per language -- measured at
~11s either way at 1.55M visible senses. The SAME question asked as one
correlated EXISTS PER language, isolated, measured at 2.5ms (Postgres
correctly chooses a Nested Loop with both indexes when there's nothing to
hash-join against). 21 * 2.5ms plus per-query overhead is what this module
does instead of one clever statement.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.generated_name import Language
from app.models.semantic import Lexeme, Sense


@dataclass(frozen=True)
class LanguageRow:
    code: str
    name: str
    native_name: str | None
    script: str | None


_directory_cache: list[LanguageRow] | None = None


def _has_visible_sense(db: Session, language_id: int) -> bool:
    return db.scalar(
        select(Lexeme.id)
        .join(Sense, Sense.lexeme_id == Lexeme.id)
        .where(Lexeme.language_id == language_id,
               Sense.visibility_status == "visible")
        .limit(1)
    ) is not None


def visible_languages(db: Session) -> list[LanguageRow]:
    global _directory_cache
    if _directory_cache is not None:
        return _directory_cache

    candidates = db.execute(
        select(Language.id, Language.code, Language.name,
               Language.native_name, Language.script)
        .where(Language.code.isnot(None))
        .order_by(Language.display_order.asc().nullslast(), Language.id)
    ).all()

    _directory_cache = [
        LanguageRow(code=row.code, name=row.name,
                    native_name=row.native_name, script=row.script)
        for row in candidates
        if _has_visible_sense(db, row.id)
    ]
    return _directory_cache


def reset_caches() -> None:
    global _directory_cache
    _directory_cache = None