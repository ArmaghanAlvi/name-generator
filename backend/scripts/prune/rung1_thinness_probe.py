"""
Rung-1/2 thinness probe (READ-ONLY, no writes, Fix B evidence).

QUESTION: how often does select_root() return a translation-linked root
backed by only ONE shared ILI, while rung 3 -- never consulted, because the
ladder short-circuits -- holds a candidate with strictly MORE shared ILIs?

Motivating case: en sense 72902 'brave' -> es. Rung 1 returns `bravo`
(1 shared ILI, i1393). Rung 3's pool holds 18 candidates including
`valiente` (2 shared: i1475 + i1393) and `intrepido`, `impavido`, `audaz`.

USAGE: python3 scripts/prune/rung1_thinness_probe.py --n 400 \
           --targets es de pl ga
"""
from __future__ import annotations

import argparse, os, sys
from collections import Counter

from sqlalchemy import func, select, text

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal
from app.models.generated_name import Language
from app.models.semantic import (
    Lexeme, Sense, SenseEmbedding, SenseSynset, SenseTranslation,
)
from app.services.root_selection import select_root, _cross_sim, _en_vector


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--targets", nargs="+", required=True)
    ap.add_argument("--examples", type=int, default=12)
    args = ap.parse_args()

    with SessionLocal() as db:
        db.execute(text("SET lock_timeout = '30s'"))
        sample = [sid for (sid,) in db.execute(
            select(Sense.id)
            .join(Lexeme, Lexeme.id == Sense.lexeme_id)
            .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
            .where(Lexeme.language_id == 1, Sense.visibility_status == "visible")
            .order_by(func.random()).limit(args.n)
        )]

        for code in args.targets:
            lang = db.scalars(select(Language).where(Language.code == code)).first()
            if lang is None:
                print(f"{code}: no such language"); continue
            tally = Counter()
            shown = 0
            print(f"\n===== {code}")
            for sid in sample:
                rc = select_root(db, english_sense_id=sid, language_code=code,
                                 include_vector_fallback=False)
                if rc is None or rc.rung not in ("corroborated", "primary"):
                    tally["not_rung12"] += 1
                    continue
                tally["rung12_hits"] += 1

                en_ilis = {i for (i,) in db.execute(
                    select(SenseSynset.ili).where(SenseSynset.sense_id == sid))}
                if not en_ilis:
                    tally["winner_no_ili"] += 1
                    continue
                win_n = db.scalar(
                    select(func.count(func.distinct(SenseSynset.ili)))
                    .join(Sense, Sense.id == SenseSynset.sense_id)
                    .where(Sense.lexeme_id == rc.sense.lexeme_id,
                           SenseSynset.ili.in_(en_ilis))) or 0

                pool = {s: int(n) for (s, n) in db.execute(
                    select(SenseSynset.sense_id,
                           func.count(func.distinct(SenseSynset.ili)))
                    .join(Sense, Sense.id == SenseSynset.sense_id)
                    .join(Lexeme, Lexeme.id == Sense.lexeme_id)
                    .where(SenseSynset.ili.in_(en_ilis),
                           Lexeme.language_id == lang.id,
                           Sense.visibility_status == "visible")
                    .group_by(SenseSynset.sense_id))}
                pool.pop(rc.sense.id, None)
                if not pool:
                    tally["no_rung3_pool"] += 1
                    continue
                best_sid, best_n = max(pool.items(), key=lambda kv: kv[1])
                tally[f"winner_ili_{min(win_n,3)}"] += 1

                if win_n <= 1 and best_n >= 2:
                    tally["WOULD_OVERRIDE"] += 1
                    if shown < args.examples:
                        shown += 1
                        alt = db.scalars(
                            select(Sense).where(Sense.id == best_sid)).first()
                        env = _en_vector(db, sid)
                        en_lem = db.scalar(
                            select(Lexeme.lemma).join(Sense, Sense.lexeme_id == Lexeme.id)
                            .where(Sense.id == sid))
                        print(f"  en '{en_lem}' (sense {sid}): "
                              f"{rc.sense.lexeme.lemma}[{rc.rung} ili={win_n} "
                              f"sim={rc.similarity:.3f}]  ->  "
                              f"{alt.lexeme.lemma}[ili={best_n} " # type: ignore
                              f"sim={_cross_sim(db, env, best_sid):.3f}]")
            print("  " + "  ".join(f"{k}:{v}" for k, v in sorted(tally.items())))


if __name__ == "__main__":
    main()