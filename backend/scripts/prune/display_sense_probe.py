"""
Display-sense probe (READ-ONLY, no writes).

QUESTION: when select_root() lands on a lexeme carrying SEVERAL visible+
embedded senses, how often does `_display_sense` show the wrong one, and
would a LEMMA-OVERLAP term fix it?

MOTIVATION (two confirmed instances, both visible in the UI):
  ja 'shadow' (en 50303) -> the correct 'a shadow' (idx=3) scored LOWEST of
     three (0.8146) and lost by 0.0146 to a longer competing gloss.
  ko 'light'  (en 23466) -> the correct 'light' (idx=3, 5 chars, no
     synonyms) lost by 0.0170 to 'fire (as a disaster)' (20 chars, 1
     synonym).
In BOTH the correct gloss contains the queried English lemma verbatim and
the winner does not. Definition-token overlap does NOT separate them
(ko 'light' shares nothing with 'A source of illumination'); the LEMMA does.

Prints per-case detail for hand-rating and an aggregate block whose
counters reconcile -- see the 8/7/26 process note (two probes that session
produced plausible-looking wrong numbers because their counters didn't).

USAGE:
  python3 scripts/prune/display_sense_probe.py --n 300 \\
      --targets la ru ja ar ga hi sa he fa de pl es zh ko --examples 25
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter

from sqlalchemy import func, select, text

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal                         # noqa: E402
from app.models.generated_name import Language                  # noqa: E402
from app.models.semantic import Lexeme, Sense, SenseEmbedding   # noqa: E402
from app.services.root_selection import (                       # noqa: E402
    select_root, _en_vector, _cross_sim,
)
from app.utils.text import normalize_text                       # noqa: E402

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def _tokens(value: str | None) -> set[str]:
    """normalize_text() casefolds but does NOT strip punctuation, so a bare
    .split() yields 'fire;' and misses 'fire'. Tokenize on word runs."""
    return set(_TOKEN_RE.findall(normalize_text(value or "")))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--targets", nargs="+", required=True)
    ap.add_argument("--examples", type=int, default=25)
    args = ap.parse_args()

    with SessionLocal() as db:
        db.execute(text("SET lock_timeout = '30s'"))
        sample = [sid for (sid,) in db.execute(
            select(Sense.id)
            .join(Lexeme, Lexeme.id == Sense.lexeme_id)
            .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
            .where(Lexeme.language_id == 1,
                   Sense.visibility_status == "visible")
            .order_by(func.random()).limit(args.n)
        )]

        for code in args.targets:
            lang = db.scalars(
                select(Language).where(Language.code == code)).first()
            if lang is None:
                print(f"{code}: no such language"); continue

            t = Counter()
            gaps: list[float] = []
            shown = 0
            print(f"\n===== {code}")

            for sid in sample:
                rc = select_root(db, english_sense_id=sid,
                                 language_code=code,
                                 include_vector_fallback=False)
                if rc is None:
                    t["no_root"] += 1
                    continue
                if rc.rung in ("ili", "ili_override"):
                    # rung 3 selects SENSE ids directly -- _display_sense is
                    # never called, so these are out of scope by construction.
                    t["rung3_out_of_scope"] += 1
                    continue

                rows = [r for (r,) in db.execute(
                    select(Sense.id)
                    .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
                    .where(Sense.lexeme_id == rc.sense.lexeme_id,
                           Sense.visibility_status == "visible")
                )]
                if len(rows) < 2:
                    t["single_sense_lexeme"] += 1
                    continue

                t["cases"] += 1
                env = _en_vector(db, sid)
                en_lemma = db.scalar(
                    select(Lexeme.lemma).join(Sense, Sense.lexeme_id == Lexeme.id)
                    .where(Sense.id == sid))
                key = _tokens(en_lemma)

                scored = []
                for i in rows:
                    s = db.scalars(select(Sense).where(Sense.id == i)).first()
                    if s is None:
                        continue
                    scored.append((_cross_sim(db, env, i), i, s,
                                   bool(key) and key <= _tokens(s.definition)))
                scored.sort(key=lambda e: -e[0])
                top_sim, top_id, top_s, top_hit = scored[0]

                # Independent of lemma overlap: is the WINNER short relative
                # to its siblings? Motivated by a case found incidentally
                # while verifying Step 1 (en 'take' 5407 -> pl wziąć):
                # 'to take (to get hit)' (4 words) beat 'to take (to grab
                # with the hands)' (6 words) and 'to take, to take away
                # (to deprive of)' (7 words) on cosine alone. NEITHER
                # candidate contained the English lemma as a token in that
                # case, so a lemma-overlap bonus would NOT have fixed it --
                # this counter exists to size that gap separately.
                lens = [len(_tokens(s.definition)) for _, _, s, _ in scored]
                if lens and lens[0] == min(lens) and len(set(lens)) > 1:
                    t["winner_is_shortest_gloss"] += 1

                # The population a lemma-overlap bonus could act on: the
                # chosen sense does NOT gloss the query word, some other
                # sense of the same lexeme DOES.
                others = [e for e in scored[1:] if e[3]]
                if top_hit:
                    t["chosen_glosses_lemma"] += 1
                elif not others:
                    t["no_lemma_anywhere"] += 1
                else:
                    t["BONUS_POPULATION"] += 1
                    gap = top_sim - others[0][0]
                    gaps.append(gap)
                    if shown < args.examples:
                        shown += 1
                        ed = db.scalar(
                            select(Sense.definition).where(Sense.id == sid))
                        print(f"  en {en_lemma!r}({sid}) [{rc.rung}]: "
                              f"{(ed or '')[:52]}")
                        for sim, i, s, hit in scored[:5]:
                            mark = " <== SHOWN" if i == top_id else ""
                            flag = " *LEMMA*" if hit else ""
                            n = len(_tokens(s.definition))
                            print(f"     {sim:.4f} idx={s.sense_index} "
                                  f"({n:2d}w) {(s.definition or '')[:44]!r}"
                                  f"{flag}{mark}")
                        print(f"     gap to best lemma-match: {gap:.4f}")

            # Reconciliation -- verify BEFORE reading anything else.
            parts = (t["chosen_glosses_lemma"] + t["no_lemma_anywhere"]
                     + t["BONUS_POPULATION"])
            ok = "OK" if parts == t["cases"] else "!! MISMATCH !!"
            print(f"  reconcile: {parts} vs cases {t['cases']}  [{ok}]")
            print("  " + "  ".join(f"{k}:{v}" for k, v in sorted(t.items())))
            if gaps:
                gaps.sort()
                q = lambda p: gaps[min(len(gaps) - 1, int(p * len(gaps)))]
                print(f"  gap p10={q(.10):.4f} p50={q(.50):.4f} "
                      f"p75={q(.75):.4f} p90={q(.90):.4f} max={gaps[-1]:.4f}")


if __name__ == "__main__":
    main()