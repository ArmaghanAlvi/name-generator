"""
Lexeme-ambiguity probe (READ-ONLY, no writes).

QUESTION
--------
`kaikki_translations.py` resolves a translation string to ONE
`target_lexeme_id` via a normalized_lemma -> id map (one value per key, no
ORDER BY). Where several lexemes share a key -- ko 불 has four (noun
fire/flame/light, noun genitalia, counter dollar, syllable MC-readings) --
the surviving id is arbitrary. Phase F runs BEFORE Phase G, so no vectors
exist at extraction time and the extractor CANNOT score. Measured exposure:
48,437 links project-wide (ar 36.5% .. ru 4.4%).

This probe scores every sibling on the key against the English query vector
and reports whether a different lexeme would win, by how much, and what it
costs to compute.

It does NOT replicate the ladder -- it isolates the rungs-1/2 lexeme choice.
Whether a changed lexeme actually changes the ROOT is measured separately by
root_selection_diff.py (Step 2) and by re-running this probe after the fix.

USAGE:
  python3 scripts/prune/lexeme_ambiguity_probe.py --targets ko ar zh es \
      --n 60 --examples 15 > /tmp/ambig_before.txt
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

from sqlalchemy import select, text

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal                            # noqa: E402
from app.models.generated_name import Language                     # noqa: E402
from app.models.semantic import Lexeme, Sense                      # noqa: E402
from app.services.root_selection import (                          # noqa: E402
    _cross_sim, _display_sense, _en_vector, select_root,
)

_SAMPLE_SQL = text("""
WITH keyc AS (
  SELECT lx.language_id, lx.normalized_lemma, count(*) AS n_lex
  FROM lexemes lx
  WHERE EXISTS (SELECT 1 FROM senses s
                WHERE s.lexeme_id = lx.id AND s.visibility_status = 'visible')
  GROUP BY 1, 2
),
candidates AS (
  SELECT DISTINCT st.sense_id
  FROM sense_translations st
  JOIN lexemes   lx  ON lx.id  = st.target_lexeme_id
  JOIN languages l   ON l.id   = st.language_id
  JOIN keyc      k   ON k.language_id = lx.language_id
                    AND k.normalized_lemma = lx.normalized_lemma
  JOIN senses    ens ON ens.id = st.sense_id
  JOIN sense_embeddings se ON se.sense_id = ens.id
  WHERE l.code = :code AND k.n_lex > 1 AND ens.visibility_status = 'visible'
)
SELECT sense_id FROM candidates
ORDER BY random()
LIMIT :n
""")


def _bucket(gap: float) -> str:
    if gap <= 0:      return "gap_0"
    if gap < 0.01:    return "gap_lt_.01"
    if gap < 0.03:    return "gap_.01_.03"
    if gap < 0.06:    return "gap_.03_.06"
    return "gap_ge_.06"


def run(codes: list[str], n: int, examples: int) -> None:
    with SessionLocal() as db:
        db.execute(text("SET lock_timeout = '30s'"))

        for code in codes:
            lang = db.scalars(
                select(Language).where(Language.code == code)).first()
            if lang is None:
                print(f"{code}: no such language")
                continue

            sample = [s for (s,) in db.execute(
                _SAMPLE_SQL, {"code": code, "n": n})]
            print(f"\n===== {code}   (sampled {len(sample)} ambiguous-key "
                  f"English senses)")
            if not sample:
                continue

            tally: Counter = Counter()
            shown = 0

            for sid in sample:
                env = _en_vector(db, sid)
                if env is None:
                    tally["no_en_vector"] += 1
                    continue

                en_row = db.execute(
                    select(Lexeme.lemma, Lexeme.part_of_speech, Sense.definition)
                    .join(Sense, Sense.lexeme_id == Lexeme.id)
                    .where(Sense.id == sid)).first()
                if en_row is None:
                    tally["en_row_missing"] += 1
                    continue
                en_lemma, en_pos, en_def = en_row

                linked = [i for (i,) in db.execute(text("""
                    SELECT DISTINCT target_lexeme_id
                    FROM sense_translations
                    WHERE sense_id = :sid AND language_id = :lid
                      AND target_lexeme_id IS NOT NULL
                """), {"sid": sid, "lid": lang.id})]
                if not linked:
                    tally["no_linked"] += 1
                    continue

                keys = [k for (k,) in db.execute(
                    select(Lexeme.normalized_lemma)
                    .where(Lexeme.id.in_(linked)).distinct())]
                siblings = [i for (i,) in db.execute(
                    select(Lexeme.id)
                    .where(Lexeme.language_id == lang.id,
                           Lexeme.normalized_lemma.in_(keys))
                    .order_by(Lexeme.id))]

                tally[f"cand_{min(len(siblings), 6)}"] += 1

                scored = []
                senses_touched = 0
                for lid in siblings:
                    disp = _display_sense(db, lid, env)
                    if disp is None:
                        continue
                    senses_touched += db.scalar(
                        select(Sense.id).where(
                            Sense.lexeme_id == lid,
                            Sense.visibility_status == "visible").count()
                    ) if False else 0   # counted below, kept cheap
                    scored.append((_cross_sim(db, env, disp.id), lid, disp))
                if not scored:
                    tally["no_scorable"] += 1
                    continue

                scored.sort(key=lambda e: (-e[0], e[1]))
                best_sim, best_lid, best_disp = scored[0]
                in_linked = [e for e in scored if e[1] in linked]
                if not in_linked:
                    tally["linked_unscorable"] += 1
                    continue
                cur_sim, cur_lid, cur_disp = max(in_linked, key=lambda e: e[0])

                tally["cases"] += 1
                if (en_pos or "").strip().lower() == \
                   (cur_disp.lexeme.part_of_speech or "").strip().lower():
                    tally["linked_pos_match"] += 1
                if (en_pos or "").strip().lower() == \
                   (best_disp.lexeme.part_of_speech or "").strip().lower():
                    tally["best_pos_match"] += 1

                # What select_root ACTUALLY returns, for EVERY case -- not
                # just the ones where raw argmax would swap -- so
                # shipped_pos_match is a full-population rate comparable to
                # linked_pos_match / best_pos_match above, not a rate over a
                # biased subset.
                rc = select_root(db, english_sense_id=sid,
                                 language_code=code,
                                 include_vector_fallback=False)
                shipped_lid = rc.sense.lexeme_id if rc else None
                if shipped_lid is not None:
                    assert rc is not None
                    shipped_pos = (rc.sense.lexeme.part_of_speech or "") \
                        .strip().lower()
                    if (en_pos or "").strip().lower() == shipped_pos:
                        tally["shipped_pos_match"] += 1
                else:
                    tally["shipped_no_root"] += 1
                rung = f"{rc.rung}" if rc else "NO ROOT"

                gap = best_sim - cur_sim
                tally[_bucket(gap)] += 1
                if best_lid == cur_lid:
                    tally["unchanged"] += 1
                    continue
                tally["WOULD_CHANGE"] += 1

                # Raw argmax WOULD swap here -- did the margin actually let it?
                if shipped_lid is not None:
                    if shipped_lid == cur_lid:
                        tally["margin_suppressed"] += 1
                    elif shipped_lid == best_lid:
                        tally["margin_allowed"] += 1
                    else:
                        tally["margin_other"] += 1

                if shown < examples:
                    shown += 1
                    print(f"\n  en {en_lemma!r} [{en_pos}] ({sid}): "
                          f"{(en_def or '')[:60]}")
                    print(f"     linked : {cur_disp.lexeme.lemma} "
                          f"[{cur_disp.lexeme.part_of_speech}] "
                          f"{cur_sim:.4f}  \"{(cur_disp.definition or '')[:45]}\"")
                    print(f"     best   : {best_disp.lexeme.lemma} "
                          f"[{best_disp.lexeme.part_of_speech}] "
                          f"{best_sim:.4f}  \"{(best_disp.definition or '')[:45]}\"")
                    print(f"     gap +{gap:.4f}   candidates={len(siblings)}   "
                          f"current root rung={rung}")

            print("\n  " + "  ".join(f"{k}:{v}" for k, v in sorted(tally.items())))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--targets", nargs="+", required=True)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--examples", type=int, default=15)
    a = ap.parse_args()
    run(a.targets, a.n, a.examples)


if __name__ == "__main__":
    main()