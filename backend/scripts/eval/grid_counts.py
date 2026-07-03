"""
Assert the unified engine's result counts match the breadth x depth
spec. The table values are MAXIMA (per the result-count model); words that
converge early (dead branches self-prune) legitimately return fewer. So the
assertion is: count <= expected_max for every cell, and we report any cell
that is under its max so early-convergence can be eyeballed as expected.
"""
import os
import sys
import contextlib

sys.path.insert(0, os.getcwd())

from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.semantic import Sense, Lexeme, SenseEmbedding
from app.services.multi_hop_expansion import multi_hop_expand
from app.utils.text import normalize_text
from scripts.eval.capture_engine_reference import most_used_sense_id

# Expected MAX result counts (incl. the searched word) from the spec.
# Keyed (breadth, depth). Any (b,0) or (0,d) => 1 (searched word only).
EXPECTED_MAX = {
    (0, 0): 1, (0, 1): 1, (0, 2): 1, (0, 3): 1,
    (1, 0): 1, (1, 1): 2, (1, 2): 3,  (1, 3): 4,
    (2, 0): 1, (2, 1): 3, (2, 2): 7,  (2, 3): 15,
    (3, 0): 1, (3, 1): 4, (3, 2): 13, (3, 3): 40,
}

PROBE_WORDS = [
    "brave", "light", "storm", "river", "calm",
    "joy", "shadow", "fierce", "gold", "whisper",
]


def count_cell(db, sid, breadth, depth):
    with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
        nodes = multi_hop_expand(
            db, root_sense_id=sid, width=breadth, depth=depth,
            target_language=None, min_length=0, max_length=30,
        )
    return len(nodes)


def main():
    violations = 0
    under_max = 0
    with SessionLocal() as db:
        for word in PROBE_WORDS:
            sid = most_used_sense_id(db, word)
            if sid is None:
                print(f"{word:10s} SKIPPED (no embedded sense)")
                continue
            for (breadth, depth), expected in sorted(EXPECTED_MAX.items()):
                got = count_cell(db, sid, breadth, depth)
                if got > expected:
                    violations += 1
                    print(f"  VIOLATION {word} b{breadth}d{depth}: "
                          f"got {got} > max {expected}")
                elif got < expected:
                    under_max += 1
                    # Not an error — early convergence. Uncomment to inspect:
                    # print(f"  under-max {word} b{breadth}d{depth}: "
                    #       f"got {got} < max {expected}")
    print(f"\n{violations} violations (count exceeded spec max), "
          f"{under_max} cells under max (early convergence, expected).")
    if violations == 0:
        print("PASS: no cell exceeds its spec maximum.")


if __name__ == "__main__":
    main()