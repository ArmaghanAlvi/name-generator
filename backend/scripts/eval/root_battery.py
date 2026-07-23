"""
Root-selection battery (roadmap 5d). READ-ONLY. Two parts:
  1. Fixed concepts x targets: print each root + rung, eyeball sanity.
  2. Rung-rate census over N random embedded visible English senses:
     which rung fires per language, and how often none does.

USAGE: python3 scripts/eval/root_battery.py [--census-n 500]
"""
from __future__ import annotations

import argparse, os, sys
from collections import Counter

from sqlalchemy import func, select, text

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal                        # noqa: E402
from app.models.semantic import Lexeme, Sense, SenseEmbedding  # noqa: E402
from app.services.root_selection import select_roots           # noqa: E402

CONCEPTS = ["light", "love", "brave", "river", "dawn", "star", "hope", "storm"]
TARGETS = ["la", "ru", "ja", "ar"]


def _primary_sense_id(db, lemma: str) -> int | None:
    """Best-effort 'common sense' pick for the battery only -- NOT the
    production path (the dropdown always supplies an explicit sense_id).
    Prefers noun, since that's the dominant query pattern for this app
    (name-meaning search), then lowest lexeme id (Kaikki's own entry
    order, a weak proxy for 'more standard' etymology/POS split), then
    lowest sense_index within that lexeme."""
    return db.scalar(
        select(Sense.id)
        .join(Lexeme, Lexeme.id == Sense.lexeme_id)
        .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
        .where(Lexeme.language_id == 1, Lexeme.normalized_lemma == lemma,
               Sense.visibility_status == "visible")
        .order_by(
            (Lexeme.part_of_speech != "noun"),  # False(0) sorts before True(1)
            Lexeme.id,
            Sense.sense_index,
        ).limit(1)
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--census-n", type=int, default=500)
    args = ap.parse_args()

    with SessionLocal() as db:
        db.execute(text("SET lock_timeout = '30s'"))

        print("== fixed battery ==")
        for concept in CONCEPTS:
            sid = _primary_sense_id(db, concept)
            if sid is None:
                print(f"{concept:>8}: (no embedded visible sense)")
                continue
            roots = select_roots(db, english_sense_id=sid, language_codes=TARGETS)
            cells = []
            for code in TARGETS:
                r = roots[code]
                cells.append(f"{code}:" + (
                    f"{r.sense.lexeme.lemma}[{r.rung} {r.similarity:.2f}]"
                    if r else "--"))
            print(f"{concept:>8}: " + "   ".join(cells))

        print("\n== rung-rate census ==")
        sample = [sid for (sid,) in db.execute(
            select(Sense.id)
            .join(Lexeme, Lexeme.id == Sense.lexeme_id)
            .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
            .where(Lexeme.language_id == 1, Sense.visibility_status == "visible")
            .order_by(func.random()).limit(args.census_n)
        )]
        rates: dict[str, Counter] = {c: Counter() for c in TARGETS}
        for sid in sample:
            for code, r in select_roots(
                db, english_sense_id=sid, language_codes=TARGETS
            ).items():
                rates[code][r.rung if r else "none"] += 1
        for code in TARGETS:
            row = "  ".join(f"{k}:{rates[code].get(k,0)}"
                            for k in ("corroborated", "primary", "ili",
                                      "fallback", "none"))
            print(f"{code}: {row}   (n={len(sample)})")


if __name__ == "__main__":
    main()