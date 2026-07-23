"""
Root selection (MULTILINGUAL_EXPANSION_MODEL.md 2a): English sense -> one
root per target language, through a four-rung provenance ladder
(Breakdown 4, Step 1a):

  corroborated  translation link AND shared ILI
  primary       translation link only
  ili           shared ILI only (no translation link)
  fallback      cross-language vector NN above the PAIR floor (Step 4);
                a pair whose floor is None has no fallback rung.

Tie-break within a rung: embedded+visible display sense required; then
cross-language cosine to the English sense's stored vector (valid WITHIN one
language pair -- constant anisotropy offset; never compared across pairs);
then lowest sense_index, then lemma (determinism).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.generated_name import Language
from app.models.semantic import (
    Lexeme, Sense, SenseEmbedding, SenseSynset, SenseTranslation,
)

from app.services.vector_scope import scoped_vector_scan

# Pair floors from scripts/eval/root_link_calibration.py (random p99 rule,
# Breakdown 4 Step 4b). None = no fallback rung for that pair.
# FILL FROM /tmp/root_calibration.txt BEFORE FIRST USE.
ROOT_FALLBACK_FLOORS: dict[str, float | None] = {
    "la": 0.882,
    "ru": 0.875,
    "ja": 0.865,
    "ar": 0.875,
}

# Guard for PIVOT-RESCUED roots (Breakdown 4, Step 6 revision). Set at each
# pair's POSITIVE p10 from root_link_calibration.py -- NOT random p99.
# Rationale: a rescued root is already backed by a translation link or shared
# ILI (hard evidence); the similarity check here only catches a synonym that
# drifted somewhere unrelated. Reusing the fallback floor would reject most
# CORRECT rescues -- e.g. la's fallback floor 0.882 sits ABOVE la's positive
# median 0.850, so lux/lumen (max 0.858 vs 'light') would fail it despite
# being right. Strictness is calibrated to the rung's evidence, not shared.
ROOT_RESCUE_FLOORS: dict[str, float | None] = {
    "la": 0.799,
    "ru": 0.800,
    "ja": 0.822,
    "ar": 0.784,
}


@dataclass(frozen=True)
class RootCandidate:
    language_code: str
    sense: Sense
    rung: str           # corroborated | primary | ili | fallback
    similarity: float   # cross-language cosine to the EN sense (tie-break record)


def _display_sense(db: Session, lexeme_id: int) -> Sense | None:
    return db.scalars(
        select(Sense)
        .options(selectinload(Sense.lexeme).selectinload(Lexeme.language))
        .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
        .where(Sense.lexeme_id == lexeme_id,
               Sense.visibility_status == "visible")
        .order_by(Sense.sense_index).limit(1)
    ).first()


def _en_vector(db: Session, sense_id: int):
    return db.scalar(
        select(SenseEmbedding.embedding).where(SenseEmbedding.sense_id == sense_id)
    )


def _cross_sim(db: Session, en_vector, sense_id: int) -> float:
    if en_vector is None:
        return 0.0
    d = db.scalar(
        select(SenseEmbedding.embedding.cosine_distance(en_vector))
        .where(SenseEmbedding.sense_id == sense_id)
    )
    return max(0.0, 1.0 - float(d)) if d is not None else 0.0


def select_root(
    db: Session, *, english_sense_id: int, language_code: str,
) -> RootCandidate | None:
    lang = db.scalars(
        select(Language).where(Language.code == language_code)
    ).first()
    if lang is None:
        return None

    en_vector = _en_vector(db, english_sense_id)
    en_ilis = {
        ili for (ili,) in db.execute(
            select(SenseSynset.ili).where(SenseSynset.sense_id == english_sense_id)
        )
    }

    # --- rungs 1+2: translation links, split by ILI corroboration ----------
    linked_lexeme_ids = [
        lid for (lid,) in db.execute(
            select(SenseTranslation.target_lexeme_id)
            .where(SenseTranslation.sense_id == english_sense_id,
                   SenseTranslation.language_id == lang.id,
                   SenseTranslation.target_lexeme_id.isnot(None))
            .distinct()
        )
    ]
    corroborated: list[tuple[float, int, str, Sense]] = []
    primary: list[tuple[float, int, str, Sense]] = []
    for lid in linked_lexeme_ids:
        disp = _display_sense(db, lid)
        if disp is None:
            continue
        lex_ilis = {
            ili for (ili,) in db.execute(
                select(SenseSynset.ili)
                .join(Sense, Sense.id == SenseSynset.sense_id)
                .where(Sense.lexeme_id == lid)
            )
        }
        entry = (
            _cross_sim(db, en_vector, disp.id),
            -disp.sense_index,
            disp.lexeme.lemma,
            disp,
        )
        (corroborated if (en_ilis and lex_ilis & en_ilis) else primary).append(entry)

    for bucket, rung in ((corroborated, "corroborated"), (primary, "primary")):
        if bucket:
            sim, _, _, disp = max(
                bucket, key=lambda e: (e[0], e[1], [-ord(ch) for ch in e[2]])
            )
            return RootCandidate(language_code, disp, rung, sim)

    # --- rung 3: shared ILI, no translation link ---------------------------
    if en_ilis:
        ili_sense_ids = [
            sid for (sid,) in db.execute(
                select(SenseSynset.sense_id)
                .join(Sense, Sense.id == SenseSynset.sense_id)
                .join(Lexeme, Lexeme.id == Sense.lexeme_id)
                .where(SenseSynset.ili.in_(en_ilis),
                       Lexeme.language_id == lang.id)
                .distinct()
            )
        ]
        best: tuple[float, Sense] | None = None
        for sid in ili_sense_ids:
            s = db.scalars(
                select(Sense)
                .options(selectinload(Sense.lexeme).selectinload(Lexeme.language))
                .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
                .where(Sense.id == sid, Sense.visibility_status == "visible")
            ).first()
            if s is None:
                continue
            sim = _cross_sim(db, en_vector, s.id)
            if best is None or sim > best[0]:
                best = (sim, s)
        if best is not None:
            return RootCandidate(language_code, best[1], "ili", best[0])

    # --- rung 4: vector fallback above the pair floor ----------------------
    floor = ROOT_FALLBACK_FLOORS.get(language_code)
    if floor is None or en_vector is None:
        return None
    # Filtered vector query -> starvation-prone; see vector_scope.
    # strict_order: LIMIT 1 with no downstream rerank, so exact nearest
    # must hold. Measured affordable at this limit (ar 189ms worst case).
    with scoped_vector_scan(db, language_code, mode="strict_order"):
        row = db.execute(
            select(Sense, SenseEmbedding.embedding.cosine_distance(en_vector).label("d"))
            .options(selectinload(Sense.lexeme).selectinload(Lexeme.language))
            .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
            .join(Lexeme, Lexeme.id == Sense.lexeme_id)
            .where(Lexeme.language_id == lang.id,
                   Sense.visibility_status == "visible")
            .order_by("d").limit(1)
        ).first()
    if row is None:
        return None
    sense, dist = row
    sim = max(0.0, 1.0 - float(dist))
    if sim < floor:
        return None
    return RootCandidate(language_code, sense, "fallback", sim)


def select_roots(
    db: Session, *, english_sense_id: int, language_codes: list[str],
) -> dict[str, RootCandidate | None]:
    return {
        code: select_root(db, english_sense_id=english_sense_id, language_code=code)
        for code in language_codes
    }