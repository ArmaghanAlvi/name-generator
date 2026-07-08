"""Parity: Python classify() vs SQL purge_candidates, plus embed-set delta."""
from __future__ import annotations
from collections import Counter
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.db.session import SessionLocal
from app.models.semantic import Lexeme, Sense
from app.services.prune_taxonomy import classify_sense, Tier
from app.services.prune_taxonomy import TIER_A_POS, TIER_A_TAGS

SAMPLE = 40000  # random senses; raise for a fuller sweep

# Frozen copy of the PRE-refactor predicate, to detect any newly-embedded sense.
_LEGACY_POS = {"name", "symbol", "num", "character"}
_LEGACY_TAGS = {
    "form-of","alt-of","alternative","clipping","ellipsis","morpheme",
    "plural-only","in-plural","abbreviation","initialism","acronym",
    "obsolete","archaic","dated","historical","nonstandard","dialectal",
    "derogatory","vulgar","slang",
}
_ALT_TAGS = {"alt-of", "alternative"}
_OTHER_TIER_A_TAGS = TIER_A_TAGS - _ALT_TAGS

def legacy_worthy(s: Sense) -> bool:
    lem = (s.lexeme.lemma or "").strip()
    if len((s.definition or "").strip()) < 3: return False
    if (s.lexeme.part_of_speech or "").strip().lower() in _LEGACY_POS: return False
    if {str(t).strip().lower() for t in (s.raw_tags or [])} & _LEGACY_TAGS: return False
    if not lem or any(c.isspace() or c.isdigit() for c in lem): return False
    if not all(c.isalpha() or c in "-'" for c in lem): return False
    if lem[:1].isupper() and not lem.isupper(): return False
    return True

def is_rescued(sense: Sense, rescued_lexeme_ids: set[int]) -> bool:
    """
    Mirrors the SQL's scoped rescue: a sense is protected ONLY when it sits on
    a rescued (purely-alt, orphan-target) lexeme AND alt-of/alternative is its
    sole Tier-A trigger — no independent POS or other tag also condemns it.
    """
    if sense.lexeme_id not in rescued_lexeme_ids:
        return False
    pos = (sense.lexeme.part_of_speech or "").strip().lower()
    if pos in TIER_A_POS:
        return False
    tags = {str(t).strip().lower() for t in (sense.raw_tags or [])}
    if tags & _OTHER_TIER_A_TAGS:
        return False
    return True

def main() -> None:
    with SessionLocal() as db:
        candidate_ids = {r[0] for r in db.execute(select(Sense.id)
            .join(Sense.lexeme).where(Sense.id.in_(select(
                __import__("sqlalchemy").text("sense_id FROM purge_candidates").columns()))))} \
            if False else {r[0] for r in db.execute(
                __import__("sqlalchemy").text("SELECT sense_id FROM purge_candidates"))}
        rescued = {r[0] for r in db.execute(
            __import__("sqlalchemy").text("SELECT lexeme_id FROM prune_alt_orphan_lexemes"))}

        senses = db.scalars(
            select(Sense).options(selectinload(Sense.lexeme))
            .order_by(func.random()).limit(SAMPLE)
        ).all()

        mism, new_embeds, shrink = [], [], Counter()
        for s in senses:
            tier = classify_sense(s)
            expected_candidate = (tier is Tier.A) and not is_rescued(s, rescued)
            if expected_candidate != (s.id in candidate_ids):
                mism.append((s.id, s.lexeme.lemma, tier.value, s.id in candidate_ids))
            new_c = tier is Tier.C
            if new_c and not legacy_worthy(s):
                new_embeds.append((s.id, s.lexeme.lemma))            # MUST be empty
            if legacy_worthy(s) and not new_c:
                shrink[(s.lexeme.part_of_speech or "").lower()] += 1  # intended losses

        print(f"sampled: {len(senses)}")
        print(f"SQL/Python mismatches: {len(mism)}")
        for m in mism[:20]: print("  MISMATCH", m)
        print(f"newly-embedded (must be 0): {len(new_embeds)}")
        for m in new_embeds[:20]: print("  NEW-EMBED", m)
        print("intended embed-set shrinkage by POS:")
        for pos, n in shrink.most_common(): print(f"  {pos or '<none>'}: {n}")

if __name__ == "__main__":
    main()