from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.semantic import (
    Sense,
    SenseSelectionEvent,
    SenseSelectionStat,
)


SenseSearchKey = int


def sense_search_key_for_sense(sense: Sense) -> SenseSearchKey:
    """
    A sense_id uniquely represents language + lemma + exact meaning.
    """
    return sense.id


def record_sense_selection(
    db: Session,
    *,
    sense_id: int,
    query_text: str,
) -> None:
    stat = db.get(SenseSelectionStat, sense_id)

    if stat is None:
        stat = SenseSelectionStat(
            sense_id=sense_id,
            selection_count=0,
        )
        db.add(stat)
        db.flush()

    stat.selection_count += 1
    stat.last_selected_at = datetime.now(UTC)

    db.add(
        SenseSelectionEvent(
            sense_id=sense_id,
            query_text=query_text,
        )
    )


def get_sense_selection_counts_for_senses(
    db: Session,
    *,
    senses: Iterable[Sense],
) -> dict[SenseSearchKey, int]:
    sense_ids = {
        sense.id
        for sense in senses
    }

    if not sense_ids:
        return {}

    rows = db.scalars(
        select(SenseSelectionStat).where(
            SenseSelectionStat.sense_id.in_(sense_ids)
        )
    ).all()

    return {
        row.sense_id: row.selection_count
        for row in rows
    }