"""
Evaluation corpus: 32 shape-tagged words.

Single source of truth for the sweep harness (sweep.py) and the proxy-metric
aggregator (metrics.py, Stage 7.3). Shape tags are hand-assigned aggregation
metadata — they bucket words for per-shape metric averages, NOT imported data,
so the zero-review constraint does not apply to them.

Tags (disjoint — each word has exactly one, so per-shape averages don't
double-count):
  abstract-quality   — qualities/emotions with no concrete referent
  tight-concrete     — physical things with dense, well-populated synonym edges
  polysemous         — multiple strong senses (sense selection matters most here)
  compositional-prone— morphological-family risk (lumin-/storm-/-acious style)
  short              — <=5 chars; tests short-lemma edge behavior
"""
from __future__ import annotations

# (word, shape_tag). Order is stable; sweep.py preserves it.
CORPUS: list[tuple[str, str]] = [
    # abstract-quality (10)
    ("brave",    "abstract-quality"),
    ("calm",     "abstract-quality"),
    ("happy",    "abstract-quality"),
    ("fierce",   "abstract-quality"),
    ("hope",     "abstract-quality"),
    ("strength", "abstract-quality"),
    ("grace",    "abstract-quality"),
    ("power",    "abstract-quality"),
    ("mercy",    "abstract-quality"),
    ("wild",     "abstract-quality"),
    # tight-concrete (9)
    ("river",    "tight-concrete"),
    ("gold",     "tight-concrete"),
    ("iron",     "tight-concrete"),
    ("ocean",    "tight-concrete"),
    ("star",     "tight-concrete"),
    ("sword",    "tight-concrete"),
    ("lion",     "tight-concrete"),
    ("flame",    "tight-concrete"),
    ("whisper",  "tight-concrete"),
    # polysemous (6)
    ("light",    "polysemous"),
    ("storm",    "polysemous"),
    ("shadow",   "polysemous"),
    ("dark",     "polysemous"),
    ("fire",     "polysemous"),
    ("bright",   "polysemous"),
    # compositional-prone (5)
    ("dawn",     "compositional-prone"),
    ("frost",    "compositional-prone"),
    ("steel",    "compositional-prone"),
    ("swift",    "compositional-prone"),
    ("sneaky",   "compositional-prone"),
    # short (2)
    ("joy",      "short"),
    ("vast",     "short"),
]


def resolve_corpus(db) -> list[dict]:
    """
    Resolve every corpus word to its most-selected sense (zero-review, via
    most_used_sense_id). Returns a list of dicts with word, shape, and
    root_sense_id (None if unresolvable). Importing the resolver from
    capture_engine_reference keeps corpus resolution IDENTICAL to the oracle
    and grid_counts baseline.
    """
    # Imported here (not at module top) to avoid pulling the DB/engine stack
    # into consumers that only want the CORPUS list.
    from scripts.eval.capture_engine_reference import most_used_sense_id

    resolved = []
    for word, shape in CORPUS:
        sid = most_used_sense_id(db, word)
        resolved.append({"word": word, "shape": shape, "root_sense_id": sid})
    return resolved


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.getcwd())
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        rows = resolve_corpus(db)

    unresolved = [r["word"] for r in rows if r["root_sense_id"] is None]
    print(f"corpus size: {len(CORPUS)}")
    print(f"resolved:    {len(rows) - len(unresolved)}")
    print(f"unresolved:  {len(unresolved)}  {unresolved}")

    # Shape-bucket tally (confirms disjoint tags and counts per bucket).
    from collections import Counter
    tally = Counter(shape for _, shape in CORPUS)
    for shape, n in sorted(tally.items()):
        print(f"  {shape:20s} {n}")