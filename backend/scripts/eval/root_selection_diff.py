"""
Root-selection diff harness (READ-ONLY).

WHY THIS EXISTS
---------------
`diff_reference.py` proves an English change is byte-identical. There is no
equivalent for root selection, so any change to root_selection.py's ranking
has been unverifiable except by spot-check. This captures select_root()'s
LADDER decision (corroborated | primary | ili | llm) for a FIXED sample of
English senses x every non-English language, to JSON.

Vector fallback is EXCLUDED (include_vector_fallback=False) deliberately:
the fallback rung is floor-gated and unaffected by ranking changes, and
including it would bury real ladder movement under fallback noise.
Pivot rescue is also excluded -- it calls select_root() on SYNONYMS, so it
is affected, but second-order; measure the ladder first.

USAGE:
  # before the change
  python3 scripts/eval/root_selection_diff.py --out /tmp/roots_before.json
  # after the change -- REUSE the same sample, or the diff is meaningless
  python3 scripts/eval/root_selection_diff.py --out /tmp/roots_after.json \
      --reuse-from /tmp/roots_before.json
  # compare
  python3 scripts/eval/root_selection_diff.py --diff /tmp/roots_before.json \
      /tmp/roots_after.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import func, select, text

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal                            # noqa: E402
from app.models.generated_name import Language                     # noqa: E402
from app.models.semantic import Lexeme, Sense, SenseEmbedding      # noqa: E402
from app.services.root_selection import select_root                # noqa: E402


def _languages(db) -> list[str]:
    return [c for (c,) in db.execute(
        select(Language.code).where(Language.code != "en").order_by(Language.id)
    )]


def _sample(db, n: int) -> list[int]:
    return [sid for (sid,) in db.execute(
        select(Sense.id)
        .join(Lexeme, Lexeme.id == Sense.lexeme_id)
        .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
        .where(Lexeme.language_id == 1, Sense.visibility_status == "visible")
        .order_by(func.random()).limit(n)
    )]


def capture(out_path: str, n: int, reuse_from: str | None) -> None:
    with SessionLocal() as db:
        db.execute(text("SET lock_timeout = '30s'"))
        codes = _languages(db)
        if reuse_from:
            with open(reuse_from) as fh:
                sample = json.load(fh)["sample"]
            print(f"reusing sample of {len(sample)} from {reuse_from}")
        else:
            sample = _sample(db, n)
            print(f"fresh sample of {len(sample)}")

        rows: dict[str, dict[str, list]] = {}
        for i, sid in enumerate(sample, 1):
            cell = {}
            for code in codes:
                rc = select_root(db, english_sense_id=sid,
                                 language_code=code,
                                 include_vector_fallback=False)
                cell[code] = ([rc.sense.id, rc.sense.lexeme.lemma, rc.rung,
                               round(rc.similarity, 4)] if rc else None)
            rows[str(sid)] = cell
            if i % 50 == 0:
                print(f"  {i}/{len(sample)}")

        with open(out_path, "w") as fh:
            json.dump({"sample": sample, "languages": codes, "roots": rows},
                      fh, ensure_ascii=False, indent=1)
        print(f"wrote {out_path}")


def diff(before_path: str, after_path: str) -> None:
    with open(before_path) as fh:
        before = json.load(fh)
    with open(after_path) as fh:
        after = json.load(fh)
    if before["sample"] != after["sample"]:
        print("!! SAMPLES DIFFER -- rerun the 'after' capture with "
              "--reuse-from the 'before' file. Diff is meaningless.")
        return

    codes = before["languages"]
    changed = {c: [] for c in codes}
    total_cells = 0
    for sid, cell_b in before["roots"].items():
        cell_a = after["roots"][sid]
        for c in codes:
            total_cells += 1
            b, a = cell_b.get(c), cell_a.get(c)
            if b != a:
                changed[c].append((sid, b, a))

    n_changed = sum(len(v) for v in changed.values())
    print(f"{n_changed}/{total_cells} cells changed\n")
    for c in codes:
        if not changed[c]:
            print(f"{c}: 0 changed")
            continue
        print(f"{c}: {len(changed[c])} changed")
        for sid, b, a in changed[c][:8]:
            bs = f"{b[1]}[{b[2]} {b[3]}]" if b else "--"
            as_ = f"{a[1]}[{a[2]} {a[3]}]" if a else "--"
            print(f"   sense {sid}: {bs}  ->  {as_}")
        if len(changed[c]) > 8:
            print(f"   ... and {len(changed[c]) - 8} more")
        print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--reuse-from")
    ap.add_argument("--diff", nargs=2, metavar=("BEFORE", "AFTER"))
    args = ap.parse_args()

    if args.diff:
        diff(args.diff[0], args.diff[1])
    elif args.out:
        capture(args.out, args.n, args.reuse_from)
    else:
        ap.error("pass --out or --diff")


if __name__ == "__main__":
    main()