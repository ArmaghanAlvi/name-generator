"""
Proxy metrics.

Reads a sweep JSONL (one record per word x breadth x depth x knob-setting cell,
each with a full `results` list) and computes five per-cell proxies, then
aggregates by shape tag and flags pathological sets. Pure functions over the
JSONL — no engine, no DB — so metrics recompute instantly over any sweep file.

The five proxies (roadmap 3a):
  drift_spread       — range of origin_sim across non-root results
  convergence_rate   — actual results / theoretical max for that breadth x depth
  family_concentration — largest same-family share among non-root results (post-throttle)
  score_cliff        — largest adjacent anchored_score gap, and its rank position
  tier_composition   — edge vs vector provenance share, per depth level

Usage:
  python3 -m scripts.eval.metrics scripts/eval/sweeps/baseline-2026-07-03.jsonl
"""
from __future__ import annotations

import os
import sys
import json
import glob
from collections import defaultdict

sys.path.insert(0, os.getcwd())

from app.services.morphology import same_family
from scripts.eval.corpus import CORPUS

# Theoretical max results per (breadth, depth) — mirrors grid_counts EXPECTED_MAX
# and the result-count model. Used as convergence denominators.
EXPECTED_MAX = {
    (0, 0): 1, (0, 1): 1, (0, 2): 1, (0, 3): 1,
    (1, 0): 1, (1, 1): 2, (1, 2): 3,  (1, 3): 4,
    (2, 0): 1, (2, 1): 3, (2, 2): 7,  (2, 3): 15,
    (3, 0): 1, (3, 1): 4, (3, 2): 13, (3, 3): 40,
}

# --- Flag thresholds (roadmap 3b; generous first pass, editable in place) ---
# A set trips a flag if it crosses these. First pass is about RELATIVE
# comparison across words/configs, not absolute truth — tune freely.
FLAG_FAMILY_CONCENTRATION = 0.40   # > 40% of a set is one morphological family
FLAG_DRIFT_SPREAD_LOW = 0.03       # < 0.03 origin-sim range => set barely drifts
FLAG_SCORE_CLIFF = 0.10            # an adjacent anchored_score gap this large

# Edge provenances (vs "vector"); "selected" is the root, excluded from tiers.
_EDGE_PROVENANCES = {"kaikki_synonym", "oewn_synonym", "oewn_near_synonym"}


def _non_root(results: list[dict]) -> list[dict]:
    """Results excluding the depth-0 root (metrics describe the drift, not the seed)."""
    return [r for r in results if r.get("depth", 0) > 0]


def drift_spread(results: list[dict]) -> float:
    """Range (max-min) of origin_sim across non-root results. 0.0 if <2 results."""
    sims = [r["origin_sim"] for r in _non_root(results)]
    if len(sims) < 2:
        return 0.0
    return round(max(sims) - min(sims), 4)


def convergence_rate(results: list[dict], breadth: int, depth: int) -> float:
    """
    Actual non-root results / (theoretical max - 1) for this cell. The -1 drops
    the root from the denominator so a fully-converged set reads as 1.0 and a
    starved set reads low. Returns 0.0 for cells whose max is 1 (no expansion).
    """
    max_total = EXPECTED_MAX[(breadth, depth)]
    denom = max_total - 1
    if denom <= 0:
        return 0.0
    return round(len(_non_root(results)) / denom, 4)


def family_concentration(results: list[dict]) -> float:
    """
    Largest same-family share among non-root results. Groups by same_family
    (shared-prefix rule) greedily: each word joins the first existing cluster
    it's same_family with, else starts its own. Returns largest cluster size /
    total non-root. 0.0 if <2 results.

    KNOWN LIMITATION (inherited, intentional): same_family is the shared-prefix
    rule, so lumin- words (luminance/luminosity/luminousness) do NOT cluster
    (shared prefix 5 < length-scaled threshold 6). This metric therefore
    UNDER-reports morphological concentration for that class — by design, since
    it must measure what the engine's throttle actually groups, not an idealized
    grouping. See transfer-context sec 5; a lemmatizer would close the gap.
    """
    words = [r["word"] for r in _non_root(results)]
    if len(words) < 2:
        return 0.0
    clusters: list[list[str]] = []
    for w in words:
        placed = False
        for c in clusters:
            if same_family(w, c[0]):
                c.append(w)
                placed = True
                break
        if not placed:
            clusters.append([w])
    largest = max(len(c) for c in clusters)
    return round(largest / len(words), 4)


def score_cliff(results: list[dict]) -> dict:
    """
    Largest adjacent anchored_score gap in the ranked non-root list, plus the
    rank AFTER which it occurs (1-indexed among non-root). {"gap":0.0,"after":0}
    if <2 results. Results are assumed already in the engine's ranked order.
    NOTE (post-pivot): under tree ordering the ranked list is lineage order, so
    the largest adjacent gap often falls at a parent-group boundary, not a
    quality discontinuity. Interpret cliffs structurally, not as flat-relevance.
    """
    scores = [r["anchored_score"] for r in _non_root(results)]
    if len(scores) < 2:
        return {"gap": 0.0, "after": 0}
    gaps = [(scores[i] - scores[i + 1], i + 1) for i in range(len(scores) - 1)]
    gap, after = max(gaps, key=lambda x: x[0])
    return {"gap": round(gap, 4), "after": after}


def tier_composition(results: list[dict]) -> dict:
    """
    Per depth level, the count of edge-tier vs vector-tier vs other provenances.
    Returns {depth: {"edge": n, "vector": n, "other": n}} for depth >= 1.
    Reveals where vector fallback takes over as hops deepen.
    """
    out: dict[int, dict[str, int]] = defaultdict(
        lambda: {"edge": 0, "vector": 0, "other": 0})
    for r in _non_root(results):
        d = r["depth"]
        prov = r.get("provenance", "")
        if prov in _EDGE_PROVENANCES:
            out[d]["edge"] += 1
        elif prov == "vector":
            out[d]["vector"] += 1
        else:
            out[d]["other"] += 1
    return {d: dict(v) for d, v in sorted(out.items())}


def compute_cell_metrics(rec: dict) -> dict:
    """All five metrics for one sweep record, plus the flags it trips."""
    results = rec["results"]
    b, d = rec["breadth"], rec["depth"]
    m = {
        "word": rec["word"],
        "shape": rec["shape"],
        "breadth": b,
        "depth": d,
        "n_results": len(_non_root(results)),
        "drift_spread": drift_spread(results),
        "convergence_rate": convergence_rate(results, b, d),
        "family_concentration": family_concentration(results),
        "score_cliff": score_cliff(results),
        "tier_composition": tier_composition(results),
    }
    flags = []
    if m["family_concentration"] > FLAG_FAMILY_CONCENTRATION:
        flags.append("family-heavy")
    # Only flag low drift on sets big enough for it to mean something.
    if m["n_results"] >= 3 and m["drift_spread"] < FLAG_DRIFT_SPREAD_LOW:
        flags.append("low-drift")
    if m["score_cliff"]["gap"] >= FLAG_SCORE_CLIFF:
        flags.append("score-cliff")
    m["flags"] = flags
    return m


def aggregate_by_shape(cell_metrics: list[dict]) -> dict:
    """
    Mean of each scalar proxy per shape tag, over cells with >=2 non-root
    results (smaller cells have degenerate metrics). Score-cliff aggregated as
    mean gap. Tier composition omitted from aggregates (it's per-depth; shown
    in the detail dump instead).
    """
    buckets: dict[str, list[dict]] = defaultdict(list)
    for m in cell_metrics:
        if m["n_results"] >= 2:
            buckets[m["shape"]].append(m)

    agg = {}
    for shape, ms in sorted(buckets.items()):
        n = len(ms)
        agg[shape] = {
            "cells": n,
            "mean_drift_spread": round(sum(m["drift_spread"] for m in ms) / n, 4),
            "mean_convergence": round(sum(m["convergence_rate"] for m in ms) / n, 4),
            "mean_family_conc": round(sum(m["family_concentration"] for m in ms) / n, 4),
            "mean_score_cliff": round(sum(m["score_cliff"]["gap"] for m in ms) / n, 4),
            "flagged_cells": sum(1 for m in ms if m["flags"]),
        }
    return agg


def _fmt_tiers(tc: dict) -> str:
    """Compact tier-composition string: 'd1:e2/v0 d2:e1/v3'."""
    parts = []
    for d, c in tc.items():
        parts.append(f"d{d}:e{c['edge']}/v{c['vector']}")
    return " ".join(parts) if parts else "-"


def print_report(cell_metrics: list[dict], agg: dict, run_id: str) -> None:
    print(f"\n=== Stage 7.3 proxy metrics — run: {run_id} ===\n")
    print("NOTE: family_concentration uses the shared-prefix same_family rule; "
          "families that diverge before the length-scaled threshold "
          "(luminance/luminosity, valiant/valorous) under-report by design "
          "(see metrics.py docstring).\n")

    # Per-shape aggregate table.
    print("SHAPE AGGREGATES (cells with >=2 results):")
    hdr = f"  {'shape':20s} {'cells':>5s} {'drift':>7s} {'conv':>7s} {'famC':>7s} {'cliff':>7s} {'flagged':>7s}"
    print(hdr)
    for shape, a in agg.items():
        print(f"  {shape:20s} {a['cells']:5d} {a['mean_drift_spread']:7.3f} "
              f"{a['mean_convergence']:7.3f} {a['mean_family_conc']:7.3f} "
              f"{a['mean_score_cliff']:7.3f} {a['flagged_cells']:7d}")

    # Flagged-set detail dump.
    flagged = [m for m in cell_metrics if m["flags"]]
    print(f"\nFLAGGED SETS ({len(flagged)} cells):")
    if not flagged:
        print("  (none tripped thresholds)")
    for m in sorted(flagged, key=lambda x: (x["word"], x["breadth"], x["depth"])):
        print(f"  {m['word']:10s} b{m['breadth']}d{m['depth']} "
              f"{','.join(m['flags']):28s} "
              f"drift={m['drift_spread']:.3f} famC={m['family_concentration']:.3f} "
              f"cliff={m['score_cliff']['gap']:.3f}@{m['score_cliff']['after']} "
              f"tiers[{_fmt_tiers(m['tier_composition'])}]")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if path is None:
        candidates = sorted(glob.glob("scripts/eval/sweeps/*.jsonl"))
        if not candidates:
            raise SystemExit("no sweep JSONL found; pass a path explicitly")
        path = candidates[-1]

    records = [json.loads(l) for l in open(path)]
    run_id = records[0].get("run_id", "unknown") if records else "empty"
    cell_metrics = [compute_cell_metrics(r) for r in records]
    agg = aggregate_by_shape(cell_metrics)

    print_report(cell_metrics, agg, run_id)

    # Save metrics alongside the JSONL (roadmap 3c: "saved alongside the JSONL").
    out_path = path.replace(".jsonl", ".metrics.json")
    with open(out_path, "w") as f:
        json.dump({"run_id": run_id, "cells": cell_metrics, "shape_aggregates": agg},
                  f, indent=2)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()


