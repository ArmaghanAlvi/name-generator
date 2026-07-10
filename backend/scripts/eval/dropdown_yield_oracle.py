"""
Offline oracle: how many results does each candidate sense yield when expanded
to the configured maximum?

This is NOT a shippable ranking signal — measuring it means one full
multi_hop_expand per candidate (109 for `draw`) against a ~2.6/s ceiling. It
is measured here to answer two questions:

  1. Is yield merely a proxy for synonym_edges? (Then edge_count already
     captures it and yield is redundant.)
  2. If not, does yield predict everyday-centrality? (Then we hunt for a
     cheap proxy. If no proxy correlates, the signal is discarded.)

Writes scripts/eval/dropdown_yield.json, consumed by dropdown_rank_probe.py.

Usage:
    cd backend
    python -m scripts.eval.dropdown_yield_oracle --width 8 --depth 3
"""
from __future__ import annotations

import argparse
import json
import time

from app.db.session import SessionLocal
from app.services.multi_hop_expansion import multi_hop_expand
from app.services.sense_display import sense_display_for
from app.services.sense_lookup import fetch_sense_candidates
from scripts.eval.dropdown_gold import GOLD, SLATE

_SYNONYM_RELATIONS = frozenset({"synonym", "near_synonym"})


def _rank(values: list[float]) -> list[float]:
    """Average ranks, ties shared (needed for a correct Spearman)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)

    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        shared = (position + end) / 2.0 + 1.0
        for index in range(position, end + 1):
            ranks[order[index]] = shared
        position = end + 1

    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Pearson on ranks. Implemented locally to avoid a scipy dependency."""
    if len(xs) < 2:
        return 0.0

    rx, ry = _rank(xs), _rank(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n

    numerator = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5

    return 0.0 if dx == 0 or dy == 0 else numerator / (dx * dy)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, required=True,
                        help="set to the UI's maximum breadth")
    parser.add_argument("--depth", type=int, required=True,
                        help="set to the UI's maximum depth")
    parser.add_argument("--out", default="scripts/eval/dropdown_yield.json")
    args = parser.parse_args()

    rows: list[dict] = []
    started = time.monotonic()

    with SessionLocal() as db:
        for word, _band in SLATE:
            candidates = fetch_sense_candidates(
                db, query=word, language_code="en",
                limit=500, with_relations=True,
            )
            gold_id = GOLD[word].top1_sense_id

            for candidate in candidates:
                sense = candidate.sense
                nodes = multi_hop_expand(
                    db,
                    root_sense_id=sense.id,
                    width=args.width,
                    depth=args.depth,
                )
                display = sense_display_for(sense, candidate.override)

                rows.append({
                    "word": word,
                    "sense_id": sense.id,
                    "is_gold": sense.id == gold_id,
                    "yield_count": max(0, len(nodes) - 1),   # exclude the root
                    "synonym_edges": sum(
                        1 for r in sense.relations
                        if r.relation_type in _SYNONYM_RELATIONS
                    ),
                    "gloss_depth": len(display.group_path),
                    "sense_index": sense.sense_index,
                })

            elapsed = time.monotonic() - started
            print(f"{word:<10} {len(candidates):>4} senses   ({elapsed:.0f}s)")

    # --- Question 1: is yield just edge count? ---
    rho_edges = _spearman(
        [float(r["yield_count"]) for r in rows],
        [float(r["synonym_edges"]) for r in rows],
    )

    # --- Question 2: does yield pick the gold sense? ---
    gold_is_max = 0
    gold_percentiles: list[float] = []

    for word, _band in SLATE:
        word_rows = [r for r in rows if r["word"] == word]
        yields = [r["yield_count"] for r in word_rows]
        gold_yield = next(r["yield_count"] for r in word_rows if r["is_gold"])

        if gold_yield == max(yields):
            gold_is_max += 1

        beaten = sum(1 for y in yields if y < gold_yield)
        gold_percentiles.append(beaten / max(1, len(yields) - 1))

    summary = {
        "width": args.width,
        "depth": args.depth,
        "candidates": len(rows),
        "spearman_yield_vs_edges": round(rho_edges, 3),
        "gold_has_max_yield": f"{gold_is_max}/{len(SLATE)}",
        "mean_gold_yield_percentile": round(
            sum(gold_percentiles) / len(gold_percentiles), 3
        ),
    }

    with open(args.out, "w") as handle:
        json.dump({"summary": summary, "rows": rows}, handle, indent=2)

    print("\n" + json.dumps(summary, indent=2))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())