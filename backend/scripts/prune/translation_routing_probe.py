"""
Translation-routing probe (Breakdown 4, Step 1e). READ-ONLY.

Measures, against the real DB, everything the kaikki_translations extractor
needs decided before it exists:
  1. Volume per level: sense-level items (on Sense.raw_sense) vs entry-level
     items (on Lexeme.raw_entry), per target language code.
  2. _dis1 coverage on entry-level items, and _dis1 vs 'sense'-hint AGREEMENT:
     does the argmax sense's gloss match the hint? This validates (or kills)
     the dis1-argmax routing policy of Step 1b before anything trusts it.
  3. Hint exact-match rate (the fallback router's expected yield).
  4. Overlap: do entry-level items duplicate sense-level ones (same target
     code+word on the same entry)? Structural double-count risk report --
     the extractor's unique key dedups regardless; this just sizes it.

USAGE (from backend/): python3 scripts/prune/translation_routing_probe.py \
    [--targets la,ru,ja,ar] [--dis1-sample 2000]
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

from sqlalchemy import select, text

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal          # noqa: E402
from app.models.semantic import Lexeme, Sense    # noqa: E402
from app.utils.text import normalize_text        # noqa: E402


def _norm(s: str) -> str:
    return normalize_text(s or "").strip()


def _dis1_argmax(raw: str) -> int | None:
    """1-based index of the max weight; None if unparseable or all-zero."""
    try:
        weights = [float(w) for w in raw.split()]
    except (ValueError, AttributeError):
        return None
    if not weights or max(weights) <= 0:
        return None
    return weights.index(max(weights)) + 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--targets", default="la,ru,ja,ar")
    ap.add_argument("--dis1-sample", type=int, default=2000)
    args = ap.parse_args()
    targets = {c.strip() for c in args.targets.split(",") if c.strip()}

    with SessionLocal() as db:
        db.execute(text("SET lock_timeout = '30s'"))

        # ---- 1. sense-level volume, server-side filtered --------------------
        sense_counts: Counter = Counter()
        senses_with_tr = 0
        for (raw_sense,) in db.execute(
            select(Sense.raw_sense)
            .join(Lexeme, Lexeme.id == Sense.lexeme_id)
            .where(
                Lexeme.language_id == 1,
                text("(senses.raw_sense::jsonb) ? 'translations'"),
            )
        ).yield_per(2000):
            senses_with_tr += 1
            for tr in raw_sense.get("translations") or []:
                code = tr.get("code") or tr.get("lang_code")
                if code in targets:
                    sense_counts[code] += 1

        # ---- 2-4. entry-level: volume, dis1, hints, overlap -----------------
        entry_counts: Counter = Counter()
        entries_with_tr = 0
        dis1_present = dis1_absent = 0
        dis1_checked = dis1_agree = 0
        hint_exact = hint_miss = 0
        overlap_items = 0

        for (raw_entry,) in db.execute(
            select(Lexeme.raw_entry).where(
                Lexeme.language_id == 1,
                text("(lexemes.raw_entry::jsonb) ? 'translations'"),
            )
        ).yield_per(500):
            entries_with_tr += 1
            senses = raw_entry.get("senses") or []
            glosses_by_index: dict[int, list[str]] = {
                i: [_norm(g) for g in (sd.get("glosses") or sd.get("raw_glosses") or [])]
                for i, sd in enumerate(senses, start=1)
            }
            sense_level_keys = {
                (tr.get("code") or tr.get("lang_code"), _norm(tr.get("word") or ""))
                for sd in senses for tr in (sd.get("translations") or [])
            }
            for tr in raw_entry.get("translations") or []:
                code = tr.get("code") or tr.get("lang_code")
                if code not in targets:
                    continue
                entry_counts[code] += 1
                if (code, _norm(tr.get("word") or "")) in sense_level_keys:
                    overlap_items += 1

                hint = _norm(tr.get("sense") or "")
                hint_hit_idx = None
                if hint:
                    for idx, gl in glosses_by_index.items():
                        if any(hint == g or g.startswith(hint) or hint.startswith(g)
                               for g in gl if g):
                            hint_hit_idx = idx
                            break
                if hint_hit_idx is not None:
                    hint_exact += 1
                else:
                    hint_miss += 1

                idx = _dis1_argmax(tr.get("_dis1") or "")
                if idx is None:
                    dis1_absent += 1
                else:
                    dis1_present += 1
                    if hint_hit_idx is not None and dis1_checked < args.dis1_sample:
                        dis1_checked += 1
                        if idx == hint_hit_idx:
                            dis1_agree += 1

        print(f"senses with translations ......... {senses_with_tr}")
        print(f"entries with translations ........ {entries_with_tr}")
        for c in sorted(targets):
            print(f"  {c}: sense-level {sense_counts.get(c,0):>7}   "
                  f"entry-level {entry_counts.get(c,0):>7}   "
                  f"total {sense_counts.get(c,0)+entry_counts.get(c,0):>7}")
        tot_entry = sum(entry_counts.values())
        print(f"entry-level dis1 present ......... {dis1_present} / {tot_entry}")
        print(f"entry-level hint routed .......... {hint_exact} / {tot_entry} "
              f"(miss {hint_miss})")
        agree_pct = 100.0 * dis1_agree / dis1_checked if dis1_checked else 0.0
        print(f"dis1-vs-hint agreement ........... {dis1_agree} / {dis1_checked} "
              f"({agree_pct:.1f}%)  [both-routable sample]")
        print(f"entry/sense-level overlap items .. {overlap_items}")


if __name__ == "__main__":
    main()