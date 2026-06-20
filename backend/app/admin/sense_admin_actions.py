from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.semantic import Sense, SenseAdminOverride


def get_or_create_override(
    db: Session,
    *,
    sense_id: int,
) -> SenseAdminOverride:
    sense = db.get(Sense, sense_id)

    if sense is None:
        raise ValueError(f"Sense {sense_id} does not exist.")

    override = db.get(SenseAdminOverride, sense_id)

    if override is not None:
        return override

    override = SenseAdminOverride(
        sense_id=sense_id,
        is_hidden=False,
        notes="",
    )
    db.add(override)
    db.flush()

    return override


def update_sense_admin_override(
    db: Session,
    *,
    sense_id: int,
    is_hidden: bool | None = None,
    pinned_rank: int | None = None,
    label_override: str | None = None,
    definition_override: str | None = None,
    notes: str | None = None,
) -> SenseAdminOverride:
    override = get_or_create_override(
        db,
        sense_id=sense_id,
    )

    if is_hidden is not None:
        override.is_hidden = is_hidden
        sense = db.get(Sense, sense_id)

        if sense is not None:
            sense.visibility_status = "hidden" if is_hidden else "visible"
            sense.admin_status = "suppressed" if is_hidden else "normal"

    override.pinned_rank = pinned_rank

    if label_override is not None:
        override.label_override = label_override.strip() or None

    if definition_override is not None:
        override.definition_override = definition_override.strip() or None

    if notes is not None:
        override.notes = notes

    db.commit()
    db.refresh(override)

    return override