from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.semantic import (
    SenseSelectionEvent,
    SenseSelectionStat,
)


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

    db.add(
        SenseSelectionEvent(
            sense_id=sense_id,
            query_text=query_text,
        )
    )