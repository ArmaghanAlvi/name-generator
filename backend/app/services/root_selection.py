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

from sqlalchemy import func, select
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
    "la": 0.882, "ru": 0.875, "ja": 0.865, "ar": 0.875,
    "ga": 0.873,
    "hi": 0.867, "sa": 0.871,
    "he": 0.877, "fa": 0.871,
    "de": 0.878, "pl": 0.871,
    "es": 0.886,
    "zh": 0.862, "ko": 0.868,
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
    "la": 0.799, "ru": 0.800, "ja": 0.822, "ar": 0.784,
    "ga": 0.801,
    "hi": 0.799, "sa": 0.787,
    "he": 0.785, "fa": 0.787,
    "de": 0.815, "pl": 0.816,
    "es": 0.795,
    "zh": 0.817, "ko": 0.800,
}

# Fix B — thin-corroboration override. The ladder returns on the first
# non-empty bucket, so a SINGLE weak translation link masks rung 3 entirely.
# Measured case: en 72902 'brave' -> es returns `bravo` (1 shared ILI) while
# rung 3 holds `valiente` (2 shared: i1475 + i1393) plus intrepido/impavido/
# audaz, all unseen. Override only when corroboration is minimal on one side
# and substantially stronger on the other; the floor guard is the pair's
# positive p10, same evidence-calibrated constant Fix A uses.
_OVERRIDE_MAX_WINNER_ILI = 1    # rung-1/2 winner shares at most this many
_OVERRIDE_MIN_POOL_ILI = 2      # rung-3 candidate must share at least this


@dataclass(frozen=True)
class RootCandidate:
    language_code: str
    sense: Sense
    rung: str           # corroborated | primary | ili | fallback
    similarity: float   # cross-language cosine to the EN sense (tie-break record)


def _display_sense(db: Session, lexeme_id: int, en_vector=None) -> Sense | None:
    """Pick which sense of `lexeme_id` represents it as a root.

    WHY en_vector: `sense_index` is Kaikki's DICTIONARY order, not a relevance
    order, so this returned whichever sense the source happened to list first.
    Measured failures (Wave 6 UI check): the ja lexeme for en 'shadow' showed
    its archaic 'light' sense; the ko lexeme for en 'light' showed the 弗
    currency sense. In BOTH cases the LEXEME was correct -- only the sense
    shown was wrong, so this is a display bug, not a root-selection bug.

    The fix uses evidence the caller already holds. select_root computes
    _cross_sim(en_vector, chosen_sense) immediately AFTER this call; ranking
    the lexeme's senses by that same cosine and taking the argmax simply
    applies the evidence to CHOOSE the sense instead of only to score one
    already chosen.

    NOTE ON SCOPE: this is reached by rungs 1/2 and the llm rung, which
    resolve a LEXEME. Rung 3 (ili) and vector fallback select sense ids
    directly and already rank by cosine -- they are unaffected.

    en_vector=None reproduces the previous behaviour EXACTLY, so any caller
    without a vector is byte-identical.
    """
    stmt = (
        select(Sense)
        .options(selectinload(Sense.lexeme).selectinload(Lexeme.language))
        .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
        .where(Sense.lexeme_id == lexeme_id,
               Sense.visibility_status == "visible")
    )
    if en_vector is None:
        stmt = stmt.order_by(Sense.sense_index)
    else:
        stmt = stmt.order_by(
            SenseEmbedding.embedding.cosine_distance(en_vector),
            Sense.sense_index,          # deterministic tie-break
        )
    return db.scalars(stmt.limit(1)).first()


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
    include_vector_fallback: bool = True,
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
                   SenseTranslation.attachment != "llm",
                   SenseTranslation.target_lexeme_id.isnot(None))
            .distinct()
        )
    ]
    # Evidence-weighted ranking (Fix A). The first tuple slot is the count of
    # ILIs this candidate SHARES with the English sense -- corroboration
    # STRENGTH, not merely its presence. Measured motivation: es sense 6360
    # ('love'), where amor (4 shared ILIs, sim 0.8492) lost to querido
    # (1 shared, 0.8711) under cosine-only ranking.
    # A candidate earns its count only if it clears the pair's rescue floor
    # (positive p10); below that it ranks on similarity alone, so a
    # well-corroborated but semantically drifted candidate cannot win on
    # count alone. For the `primary` bucket every count is 0 by
    # construction, so its ordering is UNCHANGED from cosine-only.
    _floor = ROOT_RESCUE_FLOORS.get(language_code) or 0.0
    corroborated: list[tuple[int, float, int, str, Sense]] = []
    primary: list[tuple[int, float, int, str, Sense]] = []
    for lid in linked_lexeme_ids:
        disp = _display_sense(db, lid, en_vector)
        if disp is None:
            continue
        lex_ilis = {
            ili for (ili,) in db.execute(
                select(SenseSynset.ili)
                .join(Sense, Sense.id == SenseSynset.sense_id)
                .where(Sense.lexeme_id == lid)
            )
        }
        overlap = len(lex_ilis & en_ilis) if en_ilis else 0
        sim = _cross_sim(db, en_vector, disp.id)
        entry = (
            overlap if sim >= _floor else 0,
            sim,
            -disp.sense_index,
            disp.lexeme.lemma,
            disp,
        )
        (corroborated if overlap else primary).append(entry)

    linked_winner: tuple[str, int, float, Sense] | None = None
    for bucket, rung in ((corroborated, "corroborated"), (primary, "primary")):
        if bucket:
            n_shared, sim, _, _, disp = max(
                bucket,
                key=lambda e: (e[0], e[1], e[2], [-ord(ch) for ch in e[3]]),
            )
            linked_winner = (rung, n_shared, sim, disp)
            break

    # Fix B: a well-corroborated link wins outright and rung 3 is never
    # queried (unchanged hot path). Only a THIN link defers the decision.
    if linked_winner is not None and (
        not en_ilis or linked_winner[1] > _OVERRIDE_MAX_WINNER_ILI
    ):
        rung, _n, sim, disp = linked_winner
        return RootCandidate(language_code, disp, rung, sim)

    # --- rung 3: shared ILI, no translation link ---------------------------
    if en_ilis:
        # Fetch the shared-ILI COUNT per candidate, not just the id set.
        # es pools are the largest in the project (avg 1.75, 36.8% of senses
        # carry >=2 candidates, max 24) so this tie-break does real work.
        ili_overlap: dict[int, int] = {
            sid: int(n) for (sid, n) in db.execute(
                select(SenseSynset.sense_id,
                       func.count(func.distinct(SenseSynset.ili)))
                .join(Sense, Sense.id == SenseSynset.sense_id)
                .join(Lexeme, Lexeme.id == Sense.lexeme_id)
                .where(SenseSynset.ili.in_(en_ilis),
                       Lexeme.language_id == lang.id)
                .group_by(SenseSynset.sense_id)
            )
        }
        best: tuple[int, float, Sense] | None = None
        for sid, n_shared in ili_overlap.items():
            s = db.scalars(
                select(Sense)
                .options(selectinload(Sense.lexeme).selectinload(Lexeme.language))
                .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
                .where(Sense.id == sid, Sense.visibility_status == "visible")
            ).first()
            if s is None:
                continue
            sim = _cross_sim(db, en_vector, s.id)
            key = (n_shared if sim >= _floor else 0, sim)
            if best is None or key > (best[0], best[1]):
                best = (key[0], sim, s)
        if best is not None:
            n_pool, sim_pool, s_pool = best
            if linked_winner is not None:
                rung, n_win, sim_win, disp = linked_winner
                if (n_pool >= _OVERRIDE_MIN_POOL_ILI
                        and n_pool > n_win
                        and sim_pool >= _floor):
                    return RootCandidate(language_code, s_pool,
                                         "ili_override", sim_pool)
                return RootCandidate(language_code, disp, rung, sim_win)
            return RootCandidate(language_code, s_pool, "ili", sim_pool)

    # Rung 3 found nothing usable -- a thin link is still better than falling
    # through to the LLM/vector rungs.
    if linked_winner is not None:
        rung, _n, sim, disp = linked_winner
        return RootCandidate(language_code, disp, rung, sim)

    # --- rung 4: persisted LLM translation link (Breakdown 4.5) ------------
    # READS ONLY -- live proposing happens in root_llm.resolve_llm_root
    # (backfill, or query-time behind ROOT_LLM_QUERY_TIME). Fenced the other
    # way in rungs 1+2: attachment 'llm' rows never masquerade as curated.
    llm_lids = [
        lid for (lid,) in db.execute(
            select(SenseTranslation.target_lexeme_id)
            .where(SenseTranslation.sense_id == english_sense_id,
                   SenseTranslation.language_id == lang.id,
                   SenseTranslation.attachment == "llm",
                   SenseTranslation.target_lexeme_id.isnot(None))
            .distinct()
        )
    ]
    best_llm: tuple[float, Sense] | None = None
    for lid in llm_lids:
        disp = _display_sense(db, lid)
        if disp is None:
            continue
        sim = _cross_sim(db, en_vector, disp.id)
        if best_llm is None or sim > best_llm[0]:
            best_llm = (sim, disp)
    if best_llm is not None:
        return RootCandidate(language_code, best_llm[1], "llm", best_llm[0])

    if not include_vector_fallback:
        return None
    return _vector_rung(db, lang, language_code, en_vector)

def _vector_rung(db: Session, lang: Language, language_code: str,
                 en_vector) -> RootCandidate | None:
    # (the exact former rung-4 body -- floors, scoped_vector_scan
    #  strict_order, limit 1 -- byte-for-byte)
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

def vector_fallback_root(
    db: Session, *, english_sense_id: int, language_code: str,
) -> RootCandidate | None:
    """The demoted last-resort rung alone (Breakdown 4.5, decision 1a):
    measured 15-19% precision, now ordered AFTER pivoted_root rescue.
    Kept floored and labeled; candidate for per-language disablement
    (floor -> None) once Step 8's census shows its share."""
    lang = db.scalars(
        select(Language).where(Language.code == language_code)
    ).first()
    if lang is None:
        return None
    return _vector_rung(db, lang, language_code,
                        _en_vector(db, english_sense_id))

def select_roots(
    db: Session, *, english_sense_id: int, language_codes: list[str],
    include_vector_fallback: bool = True,
) -> dict[str, RootCandidate | None]:
    return {
        code: select_root(db, english_sense_id=english_sense_id,
                          language_code=code,
                          include_vector_fallback=include_vector_fallback)
        for code in language_codes
    }