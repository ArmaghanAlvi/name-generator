"""
Sweep harness.
Runs multi_hop_expand over corpus x cells x knob-setting and writes one JSONL
line PER CELL (a full result set), not per result node — because every Stage 7.3
proxy metric (drift spread, convergence, family concentration, score-cliff, tier
composition) is a per-result-set computation, so the cell is the natural unit.

Each line captures raw `score` and `origin_sim` alongside `anchored_score`, so
metrics need no re-run. Read-only against the engine and DB.

Usage:
  python3 -m scripts.eval.sweep --run-id baseline-YYYY-MM-DD --cells full
  python3 -m scripts.eval.sweep --run-id alpha-0.50 --cells sweep \\
      --knobs alpha_origin=0.50
"""
from __future__ import annotations

import os
import sys
import json
import argparse
import contextlib

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal
from app.services.multi_hop_expansion import multi_hop_expand
from scripts.eval.corpus import CORPUS, resolve_corpus

# Full 16-cell grid (matches grid_counts.py EXPECTED_MAX keys). Doubles as a
# count-regression net over the whole corpus when used for the baseline.
FULL_CELLS = [(b, d) for b in (0, 1, 2, 3) for d in (0, 1, 2, 3)]

# Reduced sweep set (Option B): the cells that actually carry knob signal.
# Zero/low-breadth cells return 1 result or near-degenerate sets, so knob
# sweeps skip them to cut runtime ~4x.
SWEEP_CELLS = [(3, 1), (3, 2), (3, 3), (2, 2)]

# Knob names the harness accepts via --knobs. Anything omitted => engine default
# (None passed through => module constant). MIN_EXPANSION_SCORE is intentionally
# absent: it's shared with single-hop and gated to Stage 7.5.
KNOB_NAMES = ("alpha_origin", "decay_per_hop", "family_penalty_step")


def build_cell_record(node_list, *, word, shape, root_sense_id,
                      breadth, depth, knobs, run_id):
    """One JSONL record for a single (word, breadth, depth, knob-setting) cell."""
    return {
        "word": word,
        "shape": shape,
        "root_sense_id": root_sense_id,
        "breadth": breadth,
        "depth": depth,
        "knobs": knobs,              # resolved knob dict (explicit values used)
        "run_id": run_id,
        "results": [
            {
                "word": n.path[-1],
                "sense_id": n.sense.id,
                "depth": n.depth,
                "provenance": n.provenance,
                "score": round(n.score, 4),                 # raw parent-relative
                "origin_sim": round(n.origin_sim, 4),       # cosine to origin
                "anchored_score": round(n.anchored_score, 4),
                "path": list(n.path),
            }
            for n in node_list
        ],
    }


def parse_knobs(pairs: list[str]) -> dict:
    """
    Turn ['alpha_origin=0.50', 'decay_per_hop=0.01'] into a validated float dict.
    Only KNOB_NAMES are accepted; unknown keys are a hard error (a typo'd knob
    would otherwise silently sweep nothing).
    """
    knobs = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"--knobs entry must be key=value, got: {p!r}")
        k, v = p.split("=", 1)
        k = k.strip()
        if k not in KNOB_NAMES:
            raise SystemExit(
                f"unknown knob {k!r}; valid: {', '.join(KNOB_NAMES)}")
        knobs[k] = float(v)
    return knobs


def run_cell(db, sid, breadth, depth, knobs):
    """Call the engine for one cell, passing only the overridden knobs."""
    with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
        return multi_hop_expand(
            db, root_sense_id=sid, width=breadth, depth=depth,
            target_language=None, min_length=0, max_length=30,
            **knobs,  # only overridden knobs; omitted => engine default
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True,
                    help="label stamped on every record (e.g. baseline-2026-07-03)")
    ap.add_argument("--cells", choices=("full", "sweep"), default="sweep",
                    help="full=16-cell grid (baseline); sweep=reduced set (knob sweeps)")
    ap.add_argument("--knobs", nargs="*", default=[],
                    help="knob overrides, e.g. --knobs alpha_origin=0.50")
    ap.add_argument("--out", default=None,
                    help="output path; default scripts/eval/sweeps/<run-id>.jsonl")
    args = ap.parse_args()

    cells = FULL_CELLS if args.cells == "full" else SWEEP_CELLS
    knobs = parse_knobs(args.knobs)

    # Record the FULL resolved knob set (overrides + defaults) so each line is
    # self-describing for 7.3/7.5 without needing the CLI invocation.
    from app.services.multi_hop_expansion import (
        ALPHA_ORIGIN, DECAY_PER_HOP, FAMILY_PENALTY_STEP,
    )
    resolved_knobs = {
        "alpha_origin": knobs.get("alpha_origin", ALPHA_ORIGIN),
        "decay_per_hop": knobs.get("decay_per_hop", DECAY_PER_HOP),
        "family_penalty_step": knobs.get("family_penalty_step", FAMILY_PENALTY_STEP),
    }

    out_path = args.out or f"scripts/eval/sweeps/{args.run_id}.jsonl"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    n_lines = 0
    skipped = []
    with SessionLocal() as db, open(out_path, "w") as f:
        resolved = resolve_corpus(db)
        for row in resolved:
            word, shape, sid = row["word"], row["shape"], row["root_sense_id"]
            if sid is None:
                skipped.append(word)
                continue
            for breadth, depth in cells:
                nodes = run_cell(db, sid, breadth, depth, knobs)
                rec = build_cell_record(
                    nodes, word=word, shape=shape, root_sense_id=sid,
                    breadth=breadth, depth=depth, knobs=resolved_knobs,
                    run_id=args.run_id,
                )
                f.write(json.dumps(rec) + "\n")
                n_lines += 1

    print(f"wrote {out_path}")
    print(f"lines: {n_lines}  (words={len(resolved) - len(skipped)}, "
          f"cells={len(cells)})")
    if skipped:
        print(f"SKIPPED (no embedded sense): {skipped}")


if __name__ == "__main__":
    main()