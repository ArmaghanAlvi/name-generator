"""
Per-rung root-quality sampler (READ-ONLY).

QUESTION: for one language, is a given rung's OUTPUT actually better than
another rung's? The census counts how often each rung FIRES; it says nothing
about whether the roots it produces are right. Motivating case: zh resolves
`love` -> 甜心 (sweetheart) and `star` -> 天才 (genius) via `ili`, while its
`corroborated`/`primary` rungs got brave/dawn/hope right in the same session.
Hypothesis: omw-cmn's 8,315 memberships (10.42% member match, batch low) leave
rung 3's candidate pool too thin for it to outrank rung 2 for this language.

Prints English lemma + gloss next to the chosen root + ITS gloss, grouped by
rung, for hand-rating. Deliberately no automatic scoring -- there is no
ground truth here, that is the point.

USAGE:
  python3 scripts/prune/rung_precision_probe.py --lang zh --n 40 \
      --rungs corroborated primary ili
"""
from __future__ import annotations

import argparse, os, sys
from collections import defaultdict

from sqlalchemy import func, select, text

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal                        # noqa: E402
from app.models.semantic import Lexeme, Sense, SenseEmbedding  # noqa: E402
from app.services.root_selection import select_root            # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lang", required=True)
    ap.add_argument("--n", type=int, default=40,
                    help="target samples PER RUNG")
    ap.add_argument("--rungs", nargs="+",
                    default=["corroborated", "primary", "ili"])
    ap.add_argument("--pool", type=int, default=4000,
                    help="English senses to walk before giving up")
    args = ap.parse_args()

    want = set(args.rungs)
    buckets: dict[str, list] = defaultdict(list)

    with SessionLocal() as db:
        db.execute(text("SET lock_timeout = '30s'"))
        sample = [sid for (sid,) in db.execute(
            select(Sense.id)
            .join(Lexeme, Lexeme.id == Sense.lexeme_id)
            .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
            .where(Lexeme.language_id == 1,
                   Sense.visibility_status == "visible")
            .order_by(func.random()).limit(args.pool)
        )]

        for sid in sample:
            if all(len(buckets[r]) >= args.n for r in want):
                break
            rc = select_root(db, english_sense_id=sid,
                             language_code=args.lang,
                             include_vector_fallback=False)
            if rc is None or rc.rung not in want:
                continue
            if len(buckets[rc.rung]) >= args.n:
                continue
            en_lem = db.scalar(
                select(Lexeme.lemma).join(Sense, Sense.lexeme_id == Lexeme.id)
                .where(Sense.id == sid))
            en_def = db.scalar(select(Sense.definition).where(Sense.id == sid))
            buckets[rc.rung].append(
                (sid, en_lem, (en_def or "")[:60],
                 rc.sense.lexeme.lemma, (rc.sense.definition or "")[:50],
                 rc.similarity))

        for rung in args.rungs:
            rows = buckets.get(rung, [])
            print(f"\n===== {args.lang} / {rung}  (n={len(rows)})")
            for sid, en_lem, en_def, lem, defn, sim in rows:
                print(f"  [{sid}] {en_lem:<16} {en_def}")
                print(f"        -> {lem}  ({sim:.3f})  {defn}")


if __name__ == "__main__":
    main()