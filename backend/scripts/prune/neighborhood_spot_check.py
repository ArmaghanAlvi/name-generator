"""
Qualitative neighborhood read for one lemma in one language (roadmap 4c).

Takes the PRIMARY embedded visible sense of (lemma, language), uses its own
stored vector as the query, and prints the nearest same-language neighbors.
This is a read, not a gate — the quantitative gate is the calibration script.

USAGE (from backend/):
  python3 scripts/prune/neighborhood_spot_check.py --language-code la --lemma lux
"""
from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import select, text

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal                       # noqa: E402
from app.models.generated_name import Language                # noqa: E402
from app.models.semantic import Lexeme, Sense, SenseEmbedding  # noqa: E402
from app.utils.text import normalize_lemma                     # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--language-code", required=True)
    ap.add_argument("--lemma", required=True)
    ap.add_argument("--k", type=int, default=15)
    ap.add_argument("--exact", action="store_true",
                    help="force a sequential scan (no HNSW) — the recall control")
    ap.add_argument("--ef-search", type=int, default=None,
                    help="raise hnsw.ef_search for this query only")
    ap.add_argument("--any-language", action="store_true",
                    help="drop the language filter; tag each hit and report "
                         "the language composition of the raw neighborhood")
    args = ap.parse_args()

    with SessionLocal() as db:
        if args.exact:
            # Exact brute-force scan: the recall CONTROL. If this returns k
            # rows and the HNSW path returns fewer, the index is starving on
            # post-filtering, not the data being absent.
            db.execute(text("SET LOCAL enable_indexscan = off"))
            db.execute(text("SET LOCAL enable_bitmapscan = off"))
        elif args.ef_search:
            db.execute(text(f"SET LOCAL hnsw.ef_search = {int(args.ef_search)}"))

        lang = db.scalars(
            select(Language).where(Language.code == args.language_code)
        ).first()
        if lang is None:
            raise SystemExit(f"No language {args.language_code!r}")

        norm = normalize_lemma(args.lemma, lang.code)
        anchor = db.execute(
            select(Sense, SenseEmbedding.embedding, Lexeme.lemma)
            .join(Lexeme, Lexeme.id == Sense.lexeme_id)
            .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
            .where(
                Lexeme.language_id == lang.id,
                Lexeme.normalized_lemma == norm,
                Sense.visibility_status == "visible",
            )
            .order_by(Sense.sense_index)
            .limit(1)
        ).first()
        if anchor is None:
            raise SystemExit(f"No embedded visible sense for {args.lemma!r} in {lang.code}")
        anchor_sense, anchor_vec, anchor_lemma = anchor
        print(f"anchor: {anchor_lemma} — {anchor_sense.definition[:90]}\n")

        distance = SenseEmbedding.embedding.cosine_distance(anchor_vec)
        stmt = (
            select(Lexeme.lemma, Sense.definition, Language.code, distance.label("d"))
            .join(Sense, Sense.id == SenseEmbedding.sense_id)
            .join(Lexeme, Lexeme.id == Sense.lexeme_id)
            .join(Language, Language.id == Lexeme.language_id)
            .where(
                Lexeme.id != anchor_sense.lexeme_id,
                Sense.visibility_status == "visible",
            )
            .order_by(distance)
            .limit(args.k)
        )
        if not args.any_language:
            # The scoped surface the engine actually queries.
            stmt = stmt.where(Lexeme.language_id == lang.id)
        rows = db.execute(stmt).all()

        from collections import Counter
        composition: Counter = Counter()
        for lemma, definition, code, d in rows:
            composition[code] += 1
            tag = f"[{code}] " if args.any_language else ""
            print(f"  {1.0 - float(d):.4f}  {tag}{lemma:<20} {(definition or '')[:66]}")

        # Returned-vs-requested makes index starvation visible instead of
        # silent: fewer rows than k, with no score cutoff anywhere in this
        # script, means the scan stopped early — not that neighbors are absent.
        print(f"\nreturned {len(rows)} of k={args.k}")
        if args.any_language:
            print("composition: " + "  ".join(
                f"{c}:{n}" for c, n in composition.most_common()
            ))


if __name__ == "__main__":
    main()