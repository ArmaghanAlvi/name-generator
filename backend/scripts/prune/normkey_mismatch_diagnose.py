"""Diagnose normkey parity mismatches: exact codepoints, sense state, and
what classify() would do with the row today. Read-only.

Answers two questions the parity check can't:
  1. WHICH codepoint differs (the check prints stored, never the new value).
  2. WHY the row is in the DB at all, if rule 7 should have dropped it.
"""
import os
import sys
import unicodedata

from sqlalchemy import func, select

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal          # noqa: E402
from app.models.generated_name import Language   # noqa: E402
from app.models.semantic import Lexeme, Sense    # noqa: E402
from app.services.prune_taxonomy import classify  # noqa: E402
from app.utils.text import normalize_lemma, normalize_text  # noqa: E402


def cps(s: str) -> str:
    return " ".join(f"U+{ord(c):04X}[{unicodedata.category(c)}]" for c in s)


with SessionLocal() as db:
    codes: dict[int, str | None] = {
        i: c for i, c in db.execute(select(Language.id, Language.code)).all()
    }

    for lex_id, lemma, stored, lang_id, pos in db.execute(
        select(Lexeme.id, Lexeme.lemma, Lexeme.normalized_lemma,
               Lexeme.language_id, Lexeme.part_of_speech)
    ).yield_per(5000):
        new = normalize_lemma(lemma, codes.get(lang_id))
        if new == stored:
            continue

        n_senses = db.scalar(
            select(func.count()).select_from(Sense)
            .where(Sense.lexeme_id == lex_id)
        )
        vis = db.execute(
            select(Sense.visibility_status, func.count())
            .where(Sense.lexeme_id == lex_id)
            .group_by(Sense.visibility_status)
        ).all()

        print("=" * 70)
        print(f"lex_id={lex_id}  lemma={lemma!r}  pos={pos!r}  lang={codes.get(lang_id)!r}")
        print(f"  lemma cps  : {cps(lemma)}")
        print(f"  stored key : {stored!r}")
        print(f"  stored cps : {cps(stored)}")
        print(f"  normalize_text(lemma) : {normalize_text(lemma)!r}")
        print(f"  canonical (new key)   : {new!r}")
        print(f"  senses={n_senses}  by_visibility={vis}")

        s = db.scalars(
            select(Sense).where(Sense.lexeme_id == lex_id)
            .order_by(Sense.sense_index).limit(1)
        ).first()
        if s is not None:
            tier = classify(pos or "", s.raw_tags or [], lemma, s.definition or "")
            print(f"  classify(first sense) -> Tier {tier.value}   def={s.definition!r:.60}")
        else:
            print("  ORPHAN LEXEME: zero senses (purge residue)")