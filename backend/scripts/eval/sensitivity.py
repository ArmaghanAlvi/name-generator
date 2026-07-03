"""
Knob sensitivity analysis.

For each knob, compares proxy metrics across its swept values (others held at
default) against the center run. Answers 5b: which proxies shift, by how much,
on which shapes. Reuses metrics.py's pure functions — no engine, no DB.

A knob "moves" a proxy if the shape-aggregated metric changes by more than a
small epsilon across its range. Knobs flat across all proxies get frozen.

Usage:
  python3 -m scripts.eval.sensitivity
"""
from __future__ import annotations

import os
import sys
import json

sys.path.insert(0, os.getcwd())

from scripts.eval.metrics import compute_cell_metrics, aggregate_by_shape

SWEEP_DIR = "scripts/eval/sweeps"

# The center run all knobs share, and each knob's off-center points.
CENTER = "knob-center"
KNOB_RUNS = {
    "alpha_origin":        ["alpha-0.20", CENTER, "alpha-0.50"],
    "decay_per_hop":       ["decay-0.00", CENTER, "decay-0.05"],
    "family_penalty_step": ["family-0.00", CENTER, "family-0.06"],
}

# A shape-aggregated proxy must move more than this to count as "moved".
MOVE_EPSILON = 0.02

# Proxy fields in the shape-aggregate to track for movement.
TRACKED = ["mean_drift_spread", "mean_convergence",
           "mean_family_conc", "mean_score_cliff"]


def load_aggregates(run_id: str) -> dict:
    """Compute shape aggregates for one sweep file."""
    path = f"{SWEEP_DIR}/{run_id}.jsonl"
    records = [json.loads(l) for l in open(path)]
    cell_metrics = [compute_cell_metrics(r) for r in records]
    return aggregate_by_shape(cell_metrics)


def _load_records(run_id: str) -> list[dict]:
    """Raw sweep records for a run (unlike load_aggregates, no metric compute)."""
    path = f"{SWEEP_DIR}/{run_id}.jsonl"
    return [json.loads(l) for l in open(path)]


def r_key(rec: dict) -> tuple:
    """Cell identity: (word, breadth, depth). Stable across runs of same cell."""
    return (rec["word"], rec["breadth"], rec["depth"])


def _cell_rank_displacement(center_results: list[dict],
                            other_results: list[dict]) -> float | None:
    """
    Mean absolute rank change of non-root results between two runs of the SAME
    cell. For each word present in BOTH runs' non-root results, |rank_center -
    rank_other|; averaged over shared words. None if <2 shared words (nothing
    to reorder).

    Ranks are 0-indexed position in the engine's returned order (which IS the
    anchored_score order). Membership rarely changes across knobs (same words,
    different order), so shared-word overlap is high and this captures the
    reshuffle the order-invariant proxies miss.
    """
    def rank_map(results):
        nonroot = [r for r in results if r.get("depth", 0) > 0]
        return {r["word"]: i for i, r in enumerate(nonroot)}

    c_rank = rank_map(center_results)
    o_rank = rank_map(other_results)
    shared = set(c_rank) & set(o_rank)
    if len(shared) < 2:
        return None
    total = sum(abs(c_rank[w] - o_rank[w]) for w in shared)
    return round(total / len(shared), 4)


def analyze_knob_displacement(knob: str, run_ids: list[str]) -> dict:
    """
    Rank-displacement of each off-center run vs. the center, aggregated by shape.
    run_ids is [low, center, high]; center is the middle entry. Returns per-shape
    mean displacement for low-vs-center and high-vs-center.
    """
    center_id = run_ids[len(run_ids) // 2]  # middle entry is the center
    runs = {rid: {r_key(r): r for r in _load_records(rid)}
            for rid in run_ids}

    by_shape_disp: dict[str, list[float]] = {}
    center_cells = _load_records(center_id)
    for crec in center_cells:
        key = r_key(crec)
        shape = crec["shape"]
        for rid in run_ids:
            if rid == center_id:
                continue
            orec = runs[rid].get(key)
            if orec is None:
                continue
            disp = _cell_rank_displacement(crec["results"], orec["results"])
            if disp is None:
                continue
            by_shape_disp.setdefault(shape, []).append(disp)

    shape_means = {
        shape: round(sum(v) / len(v), 4)
        for shape, v in sorted(by_shape_disp.items()) if v
    }
    overall = (round(sum(sum(v) for v in by_shape_disp.values())
                     / sum(len(v) for v in by_shape_disp.values()), 4)
               if by_shape_disp else 0.0)
    return {"knob": knob, "shape_displacement": shape_means, "overall": overall}


def analyze_knob(knob: str, run_ids: list[str]) -> dict:
    """
    For one knob, load aggregates at each swept value and compute, per shape
    per proxy, the range (max-min) across the swept values. A proxy "moves" for
    a shape if that range exceeds MOVE_EPSILON.
    """
    aggs = {rid: load_aggregates(rid) for rid in run_ids}
    shapes = set()
    for a in aggs.values():
        shapes.update(a.keys())

    movements = []  # (shape, proxy, range, values-by-run)
    for shape in sorted(shapes):
        for proxy in TRACKED:
            vals = []
            for rid in run_ids:
                shape_agg = aggs[rid].get(shape)
                vals.append(shape_agg[proxy] if shape_agg else None)
            present = [v for v in vals if v is not None]
            if len(present) < 2:
                continue
            rng = round(max(present) - min(present), 4)
            if rng > MOVE_EPSILON:
                movements.append({
                    "shape": shape, "proxy": proxy, "range": rng,
                    "values": dict(zip(run_ids, vals)),
                })
    movements.sort(key=lambda m: m["range"], reverse=True)
    return {"knob": knob, "run_ids": run_ids, "movements": movements}


def print_report(analyses: list[dict]) -> None:
    print("\n=== Stage 7.5 knob sensitivity ===")
    print(f"(a proxy 'moves' if its shape-aggregate range > {MOVE_EPSILON})\n")
    for a in analyses:
        knob = a["knob"]
        movements = a["movements"]
        if not movements:
            print(f"{knob}: FLAT — no proxy moved > {MOVE_EPSILON} on any shape. "
                  f"=> freeze at default.\n")
            continue
        print(f"{knob}: MOVES {len(movements)} shape/proxy pairs")
        for m in movements:
            vals = "  ".join(
                f"{rid.split('-')[-1]}={v:.3f}" if v is not None else f"{rid}=--"
                for rid, v in m["values"].items())
            print(f"  {m['shape']:20s} {m['proxy']:20s} range={m['range']:.3f}  [{vals}]")
        print()


# A knob "moves ordering" if mean rank-displacement exceeds this (positions).
DISPLACEMENT_EPSILON = 0.5


def main():
    analyses = [analyze_knob(knob, runs) for knob, runs in KNOB_RUNS.items()]
    print_report(analyses)

    print("\n=== Rank-displacement (ordering sensitivity) ===")
    print(f"(a knob 'moves ordering' if mean displacement > "
          f"{DISPLACEMENT_EPSILON} positions)\n")
    disp_analyses = []
    for knob, runs in KNOB_RUNS.items():
        d = analyze_knob_displacement(knob, runs)
        disp_analyses.append(d)
        verdict = ("MOVES ORDERING" if d["overall"] > DISPLACEMENT_EPSILON
                   else "flat ordering")
        print(f"{knob}: {verdict}  (overall mean disp={d['overall']})")
        for shape, disp in d["shape_displacement"].items():
            print(f"    {shape:20s} {disp:.3f}")
        print()

    out_path = f"{SWEEP_DIR}/sensitivity.json"
    with open(out_path, "w") as f:
        json.dump({
            "epsilon": MOVE_EPSILON,
            "displacement_epsilon": DISPLACEMENT_EPSILON,
            "analyses": analyses,
            "displacement": disp_analyses,
        }, f, indent=2)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()