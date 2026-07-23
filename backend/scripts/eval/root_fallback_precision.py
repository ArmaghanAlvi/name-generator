"""
Root-fallback precision probe (Breakdown 4, Step 6 revision 2).

The corrected rung census shows `fallback` carries 52-70% of all roots, and
the fixed battery shows several are WRONG (ru: хороший for 'love',
электричество for 'light', штурм for 'storm'). This measures the rung's
precision directly instead of inferring it from a distribution.

METHOD: sample English senses that HAVE a resolved translation link (so the
correct answer is KNOWN), run the fallback query as if no link existed, and
check whether its top-1 pick is one of the linked target lexemes. Agreement
is binned by similarity so a defensible floor can be READ OFF the table.

⚠ THE SAMPLE IS FAVORABLE: senses carrying translation links are common,
well-covered words. Senses where fallback ACTUALLY fires are the ones with
NO link -- rarer, thinner. So this precision is an UPPER BOUND on the
rung's real-world precision. If it is bad here, it is worse in production.

WHY NOT the Step-4b p99 rule: p99 is the 99th percentile of a SINGLE random
pair. Fallback takes the MAX over ~50K candidates, where ~1% of the pool
clears p99 by construction. A single-draw threshold applied to a
max-of-N draw is not a 1% noise budget; it is barely a filter.

USAGE (from backend/):
  python3 scripts/eval/root_fallback_precision.py [--n 200] [--targets la ru ja ar]
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal                       # noqa: E402
from app.models.generated_name import Language                # noqa: E402
from app.models.semantic import (                             # noqa: E402
    Lexeme, Sense, SenseEmbedding, SenseTranslation,
)
from app.services.root_selection import ROOT_FALLBACK_FLOORS  # noqa: E402
from app.services.vector_scope import scoped_vector_scan      # noqa: E402

BINS = [(0.00, 0.85), (0.85, 0.87), (0.87, 0.89),
        (0.89, 0.91), (0.91, 1.01)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--targets", nargs="*", default=["la", "ru", "ja", "ar"])
    args = ap.parse_args()

    with SessionLocal() as db:
        db.execute(text("SET lock_timeout = '120s'"))
        for code in args.targets:
            lang = db.scalars(
                select(Language).where(Language.code == code)
            ).first()
            if lang is None:
                continue

            sense_ids = [sid for (sid,) in db.execute(
                select(SenseTranslation.sense_id)
                .where(SenseTranslation.language_id == lang.id,
                       SenseTranslation.target_lexeme_id.isnot(None))
                .group_by(SenseTranslation.sense_id)
                .order_by(func.random()).limit(args.n)
            )]

            hits = misses = skipped = 0
            by_bin: dict[tuple, list[int]] = defaultdict(list)
            floor = ROOT_FALLBACK_FLOORS.get(code)
            above_floor = 0
            examples: list[str] = []

            for sid in sense_ids:
                truth = {lid for (lid,) in db.execute(
                    select(SenseTranslation.target_lexeme_id)
                    .where(SenseTranslation.sense_id == sid,
                           SenseTranslation.language_id == lang.id,
                           SenseTranslation.target_lexeme_id.isnot(None))
                )}
                en_vec = db.scalar(
                    select(SenseEmbedding.embedding)
                    .where(SenseEmbedding.sense_id == sid)
                )
                if en_vec is None or not truth:
                    skipped += 1
                    continue

                with scoped_vector_scan(db, code, mode="strict_order"):
                    row = db.execute(
                        select(Sense,
                               SenseEmbedding.embedding
                               .cosine_distance(en_vec).label("d"))
                        .options(selectinload(Sense.lexeme))
                        .join(SenseEmbedding,
                              SenseEmbedding.sense_id == Sense.id)
                        .join(Lexeme, Lexeme.id == Sense.lexeme_id)
                        .where(Lexeme.language_id == lang.id,
                               Sense.visibility_status == "visible")
                        .order_by("d").limit(1)
                    ).first()
                if row is None:
                    skipped += 1
                    continue

                sense, dist = row
                sim = max(0.0, 1.0 - float(dist))
                ok = sense.lexeme_id in truth
                hits += ok
                misses += (not ok)
                if floor is not None and sim >= floor:
                    above_floor += 1
                for b in BINS:
                    if b[0] <= sim < b[1]:
                        by_bin[b].append(1 if ok else 0)
                        break
                if not ok and len(examples) < 8:
                    en_lemma = db.scalar(
                        select(Lexeme.lemma)
                        .join(Sense, Sense.lexeme_id == Lexeme.id)
                        .where(Sense.id == sid))
                    examples.append(
                        f"    {en_lemma} -> {sense.lexeme.lemma} "
                        f"({sim:.3f}, WRONG)")

            total = hits + misses
            pct = 100.0 * hits / total if total else 0.0
            print(f"===== en->{code}   floor={floor}")
            print(f"top-1 agrees with a link .. {hits} / {total} ({pct:.1f}%)")
            print(f"top-1 above floor ......... {above_floor} / {total}")
            print("precision by similarity bin:")
            for b in BINS:
                vals = by_bin.get(b, [])
                if not vals:
                    continue
                p = 100.0 * sum(vals) / len(vals)
                print(f"    [{b[0]:.2f},{b[1]:.2f}) n={len(vals):>4}  {p:5.1f}%")
            if examples:
                print("  sample misses:")
                print("\n".join(examples))
            print()


if __name__ == "__main__":
    main()