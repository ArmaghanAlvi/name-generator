"""Verify stored normalized_lemma values equal canonical normalize_lemma
output for every lexeme in the DB. Expect 0 mismatches (English headwords
are Mn-free, so the new key is a no-op for existing rows)."""
import os
import sys

from sqlalchemy import select

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal  # noqa: E402
from app.models.semantic import Lexeme
from app.models.generated_name import Language
from app.utils.text import normalize_lemma

with SessionLocal() as db:
    # Explicit comprehension + annotation: dict(rows) makes Pylance pick the
    # Iterable[list[bytes]] overload and infer dict[bytes, bytes].
    codes: dict[int, str | None] = {
        lang_id: code
        for lang_id, code in db.execute(
            select(Language.id, Language.code)
        ).all()
    }

    bad = 0
    samples: list[tuple[str, str]] = []
    for lemma, stored, lang_id in db.execute(
        select(Lexeme.lemma, Lexeme.normalized_lemma, Lexeme.language_id)
    ).yield_per(5000):
        if normalize_lemma(lemma, codes.get(lang_id)) != stored:
            bad += 1
            if len(samples) < 10:
                samples.append((lemma, stored))

    print(f"mismatches: {bad}")
    for s in samples:
        print("  ", s)