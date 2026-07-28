"""
Re-classify every stored sense with the CURRENT prune_taxonomy and report the
A/B/C split per language. This is the Stage 2 regression instrument: the fix
is conditioned on languages/scripts absent from the DB, so these numbers must
be byte-identical before and after.

Two modes, both needed for the three-way proof in Breakdown 1 Step 8:
  (default)          classify_sense(sense)                  -- no language
  --use-language     classify_sense(sense, lang_code=...)   -- language-aware

Before the Stage 2 signature change, --use-language is a no-op alias for the
default (classify_sense takes no lang_code yet), so this script runs unchanged
on both sides of the edit.

USAGE (from backend/):
  python3 scripts/prune/classify_db_census.py > scripts/prune/census_pre.txt
"""
from __future__ import annotations

import argparse
import inspect
import os
import sys
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import selectinload

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal            # noqa: E402
from app.models.generated_name import Language     # noqa: E402
from app.models.semantic import Lexeme, Sense      # noqa: E402
from app.services.prune_taxonomy import Tier, classify_sense  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--use-language",
        action="store_true",
        help="pass lang_code to classify_sense (no-op before Stage 2)",
    )
    args = ap.parse_args()

    # Does classify_sense accept lang_code yet? Lets one script serve both
    # sides of the Stage 2 edit without conditional imports.
    accepts_lang = "lang_code" in inspect.signature(classify_sense).parameters
    use_lang = args.use_language and accepts_lang
    print(f"mode: use_language={use_lang} (signature supports it: {accepts_lang})")

    with SessionLocal() as db:
        codes: dict[int, str | None] = {
            lang_id: code
            for lang_id, code in db.execute(
                select(Language.id, Language.code)
            ).all()
        }

        # (lang_code, tier) -> count, and (lang_code, tier, visibility) -> count
        tiers: Counter = Counter()
        detail: Counter = Counter()
        total = 0

        statement = (
            select(Sense)
            .options(selectinload(Sense.lexeme))
            .join(Lexeme, Lexeme.id == Sense.lexeme_id)
            .order_by(Sense.id)
        )
        for sense in db.scalars(statement).yield_per(5000):
            code = codes.get(sense.lexeme.language_id) or "?"
            tier = (
                classify_sense(sense, lang_code=code) if use_lang # type: ignore
                else classify_sense(sense)
            )
            tiers[(code, tier.value)] += 1
            detail[(code, tier.value, sense.visibility_status)] += 1
            total += 1

    print(f"total senses: {total}\n")
    print(f"{'lang':<6}{'A':>10}{'B':>10}{'C':>10}{'total':>10}")
    for code in sorted({k[0] for k in tiers}):
        a = tiers[(code, "A")]
        b = tiers[(code, "B")]
        c = tiers[(code, "C")]
        print(f"{code:<6}{a:>10}{b:>10}{c:>10}{a + b + c:>10}")

    print("\n--- tier x visibility_status ---")
    for key in sorted(detail):
        print(f"  {key[0]:<6} {key[1]}  {key[2]:<12} {detail[key]}")


if __name__ == "__main__":
    main()