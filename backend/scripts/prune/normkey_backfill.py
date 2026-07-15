"""Bring stored join keys into agreement with canonical normalize_lemma.

Backfills BOTH key columns together — Lexeme.normalized_lemma and
SenseRelation.target_normalized — because expansion._resolve_lemma_to_display_sense
joins one against the other. Fixing one alone would fork them.

COLLISION SEMANTICS (the reason this isn't a plain UPDATE): the canonical key
folds distinct raw references onto one key (Wiktionary spells the same word
'ʔayʔaǰuθəm' and 'ʔayʔajuθəm'; NFKC decomposes the ǰ, the strip removes the
mark, both land on 'ʔayʔajuθəm'). uq_sense_relations_edge is defined on
(from_sense_id, relation_type, provenance, target_normalized), so a merge is a
constraint violation, not an update. An edge is a POINTER to a lemma key and
expansion.py reads target_normalized alone — so two rows with the same key ARE
the same edge, and dropping the redundant one loses no reachability, only a
duplicate target_text spelling. Incumbent wins; drifted duplicate is deleted.

All reads happen before any writes, so no select autoflushes a pending UPDATE
into the constraint.

Dry-run by default; the dry run IS the measurement.
"""
import argparse
import os
import sys

from sqlalchemy import delete, select, text, update

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal          # noqa: E402
from app.models.generated_name import Language   # noqa: E402
from app.models.semantic import Lexeme, Sense, SenseRelation  # noqa: E402
from app.utils.text import normalize_lemma       # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write changes; default is dry-run (measure only)")
    args = ap.parse_args()

    with SessionLocal() as db:
        db.execute(text("SET lock_timeout = '30s'"))

        codes: dict[int, str | None] = {
            i: c for i, c in db.execute(select(Language.id, Language.code)).all()
        }

        # --- READ PHASE 1: drifted lexemes -----------------------------------
        lex_fixes: list[tuple[int, str]] = []
        for lex_id, lemma, stored, lang_id in db.execute(
            select(Lexeme.id, Lexeme.lemma, Lexeme.normalized_lemma,
                   Lexeme.language_id)
        ).yield_per(5000):
            new = normalize_lemma(lemma, codes.get(lang_id))
            if new != stored:
                lex_fixes.append((lex_id, new))

        # --- READ PHASE 2: drifted edges -------------------------------------
        # Edge language = the language of the SOURCE sense's lexeme (edges are
        # intra-language; the extractor resolves targets within one language).
        drifted: list[tuple[int, int, str, str, str]] = []  # id, from_sid, rt, prov, new
        for rel_id, from_sid, rtype, prov, tgt_text, stored, lang_id in db.execute(
            select(SenseRelation.id, SenseRelation.from_sense_id,
                   SenseRelation.relation_type, SenseRelation.provenance,
                   SenseRelation.target_text, SenseRelation.target_normalized,
                   Lexeme.language_id)
            .join(Sense, Sense.id == SenseRelation.from_sense_id)
            .join(Lexeme, Lexeme.id == Sense.lexeme_id)
        ).yield_per(5000):
            if not tgt_text:
                continue
            new = normalize_lemma(tgt_text, codes.get(lang_id))[:300]
            if new != stored:
                drifted.append((rel_id, from_sid, rtype, prov, new))

        # --- READ PHASE 3: classify each drifted edge -> update or delete -----
        # Two collision sources: an INCUMBENT row already holding the new key,
        # or a SIBLING drifted row claiming it earlier in this same run.
        claimed: set[tuple[int, str, str, str]] = set()
        rel_updates: list[tuple[int, str]] = []
        rel_deletes: list[tuple[int, str]] = []   # (id, why)

        for rel_id, from_sid, rtype, prov, new in drifted:
            key = (from_sid, rtype, prov, new)
            if key in claimed:
                rel_deletes.append((rel_id, "dup of sibling drifted row"))
                continue
            incumbent = db.scalar(
                select(SenseRelation.id).where(
                    SenseRelation.from_sense_id == from_sid,
                    SenseRelation.relation_type == rtype,
                    SenseRelation.provenance == prov,
                    SenseRelation.target_normalized == new,
                    SenseRelation.id != rel_id,
                ).limit(1)
            )
            if incumbent is not None:
                rel_deletes.append((rel_id, f"dup of existing rel {incumbent}"))
            else:
                claimed.add(key)
                rel_updates.append((rel_id, new))

        # --- REPORT -----------------------------------------------------------
        print(f"lexemes to update ............. {len(lex_fixes)}")
        print(f"edges to update .............. {len(rel_updates)}")
        print(f"edges to delete (collapsed) .. {len(rel_deletes)}")
        for i, n in lex_fixes[:20]:
            print(f"  lex {i} -> {n!r}")
        for i, n in rel_updates[:20]:
            print(f"  rel {i} -> {n!r}")
        for i, why in rel_deletes[:20]:
            print(f"  rel {i} DELETE  ({why})")

        if not args.apply:
            print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
            return

        # --- WRITE PHASE ------------------------------------------------------
        # Deletes FIRST: frees any key an update is about to claim.
        for i, _why in rel_deletes:
            db.execute(delete(SenseRelation).where(SenseRelation.id == i))
        for i, n in rel_updates:
            db.execute(update(SenseRelation).where(SenseRelation.id == i)
                       .values(target_normalized=n))
        for i, n in lex_fixes:
            db.execute(update(Lexeme).where(Lexeme.id == i)
                       .values(normalized_lemma=n))
        db.commit()
        print(f"\nApplied: {len(lex_fixes)} lexemes, "
              f"{len(rel_updates)} edge updates, {len(rel_deletes)} edge deletes.")


if __name__ == "__main__":
    main()