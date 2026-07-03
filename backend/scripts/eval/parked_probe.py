"""
Parked-synonym boundary probe.

Depth-scoped restriction collects hop edges only
from the HOPPED sense. When a hopped non-primary sense has zero own synonym
edges but its lexeme's OTHER senses have parked edges, the hop falls through to
vector-fallback and those parked edges are dropped. This probe measures how
often that happens across the baseline sweep and how much it costs (origin-sim
of the vector result vs. the best parked edge — zero hand review).

Reads the baseline JSONL for the hops actually taken; re-queries SenseRelation
with the SAME filters expansion.py uses, so "did parked edges exist?" is
answered identically to the engine.

Usage:
  python3 -m scripts.eval.parked_probe scripts/eval/sweeps/baseline-2026-07-03.jsonl
"""
from __future__ import annotations

import os
import sys
import json
import glob

sys.path.insert(0, os.getcwd())

from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.semantic import Sense, SenseRelation, SenseEmbedding

# Same edge tiers, same order as expansion.py _EDGE_TIERS.
_EDGE_TIERS = (
    ("kaikki", "synonym"),
    ("oewn", "synonym"),
    ("oewn", "near_synonym"),
)

# Cache origin vectors by root_sense_id so we embed each root once, not per hop.
_ORIGIN_CACHE: dict[int, list] = {}


def origin_vector_for_root(db, root_sense_id: int):
    """Rebuild (and cache) the origin query vector for a root sense, using the
    engine's own constructor so the scale matches the baseline exactly."""
    if root_sense_id not in _ORIGIN_CACHE:
        from app.models.semantic import Sense
        from app.services.multi_hop_expansion import _build_origin_query_vector
        root = db.get(Sense, root_sense_id)
        _ORIGIN_CACHE[root_sense_id] = _build_origin_query_vector(root)
    return _ORIGIN_CACHE[root_sense_id]


def own_edge_count(db, sense_id: int) -> int:
    """Synonym-tier edges on THIS sense (what restricted collection sees)."""
    total = 0
    for provenance, rel_type in _EDGE_TIERS:
        n = db.scalar(
            select(SenseRelation.id).where(
                SenseRelation.from_sense_id == sense_id,
                SenseRelation.relation_type == rel_type,
                SenseRelation.provenance == provenance,
            ).limit(1)
        )
        if n is not None:
            total += 1
    return total


def parked_edge_targets(db, sense_id: int) -> list[str]:
    """
    Synonym-tier target lemmas parked on OTHER senses of this sense's lexeme
    (i.e. what unrestricted root-mode collection WOULD have seen, minus this
    sense's own edges). These are the edges restriction dropped.
    """
    sense = db.get(Sense, sense_id)
    if sense is None:
        return []
    lexeme_id = sense.lexeme_id
    sibling_sense_ids = [
        sid for (sid,) in db.execute(
            select(Sense.id).where(Sense.lexeme_id == lexeme_id,
                                   Sense.id != sense_id)
        ).all()
    ]
    if not sibling_sense_ids:
        return []
    targets: list[str] = []
    for provenance, rel_type in _EDGE_TIERS:
        rows = db.execute(
            select(SenseRelation.target_normalized).where(
                SenseRelation.from_sense_id.in_(sibling_sense_ids),
                SenseRelation.relation_type == rel_type,
                SenseRelation.provenance == provenance,
            )
        ).all()
        targets.extend(norm for (norm,) in rows if norm)
    return sorted(set(targets))


def origin_sim_for_lemmas(
    db, lemmas: list[str], origin_vector,
) -> dict[str, float]:
    """
    Best origin-sim (1 - cosine distance) per lemma among its embedded, visible
    senses, scored against origin_vector. Same scale as the baseline's recorded
    origin_sim, because origin_vector is rebuilt by _build_origin_query_vector
    (deterministic: same root sense -> same query text -> same vector). Lemmas
    with no embedded visible sense are absent from the result.
    """
    from app.models.semantic import Lexeme
    if not lemmas:
        return {}
    norm_set = set(lemmas)
    rows = db.execute(
        select(
            Lexeme.normalized_lemma,
            SenseEmbedding.embedding.cosine_distance(origin_vector).label("d"),
        )
        .join(Sense, Sense.lexeme_id == Lexeme.id)
        .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
        .where(
            Lexeme.normalized_lemma.in_(norm_set),
            Sense.visibility_status == "visible",
        )
    ).all()
    best: dict[str, float] = {}
    for norm, d in rows:
        sim = max(0.0, 1.0 - float(d))
        if norm not in best or sim > best[norm]:
            best[norm] = sim
    return best


def is_parked_drop(db, result: dict) -> tuple[bool, list[str]]:
    """
    A hop (depth >= 2 result) is a parked-drop candidate when: its provenance is
    'vector' (restriction forced fallback) AND the hopped sense has zero own
    synonym edges AND its lexeme's OTHER senses carry parked synonym edges.
    Returns (is_drop, parked_targets). Depth-1 results are never parked-drops
    (level-1 root expansion is unrestricted).
    """
    if result.get("depth", 0) < 2:
        return (False, [])
    if result.get("provenance") != "vector":
        return (False, [])
    sid = result["sense_id"]
    if own_edge_count(db, sid) > 0:
        return (False, [])
    parked = parked_edge_targets(db, sid)
    return (bool(parked), parked)


def main():
    import glob
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if path is None:
        cands = sorted(glob.glob("scripts/eval/sweeps/*.jsonl"))
        if not cands:
            raise SystemExit("no sweep JSONL found; pass a path explicitly")
        path = cands[-1]

    records = [json.loads(l) for l in open(path)]
    out_path = path.replace(".jsonl", ".parked.jsonl")

    total_hops = 0            # all depth>=2 results across the sweep
    restricted_hops = 0       # depth>=2 (subject to restriction)
    flagged = []              # parked-drop hops

    with SessionLocal() as db, open(out_path, "w") as f:
        for rec in records:
            root_sid = rec["root_sense_id"]
            ov = None  # lazily built only if this record has a candidate drop
            for r in rec["results"]:
                if r.get("depth", 0) < 2:
                    continue
                total_hops += 1
                restricted_hops += 1
                drop, parked = is_parked_drop(db, r)
                if not drop:
                    continue
                # Severity: best parked-edge origin-sim vs the hop's own origin_sim.
                if ov is None:
                    ov = origin_vector_for_root(db, root_sid)
                parked_sims = origin_sim_for_lemmas(db, parked, ov)
                best_parked = max(parked_sims.values(), default=None)
                got_sim = r["origin_sim"]
                flag = {
                    "word": rec["word"],
                    "shape": rec["shape"],
                    "breadth": rec["breadth"],
                    "depth": rec["depth"],
                    "hop_word": r["word"],
                    "hop_sense_id": r["sense_id"],
                    "hop_depth": r["depth"],
                    "got_origin_sim": got_sim,
                    "parked_targets": parked,
                    "best_parked_origin_sim": (
                        round(best_parked, 4) if best_parked is not None else None),
                    "parked_better": (
                        best_parked is not None and best_parked > got_sim),
                    "path": r["path"],
                }
                flagged.append(flag)
                f.write(json.dumps(flag) + "\n")

    # --- Summary (frequency + severity) ---
    n_flagged = len(flagged)
    scorable = [x for x in flagged if x["best_parked_origin_sim"] is not None]
    better = [x for x in scorable if x["parked_better"]]
    print(f"wrote {out_path}")
    print(f"\n=== Stage 7.4 parked-synonym probe ===")
    print(f"restricted hops (depth>=2):     {restricted_hops}")
    print(f"parked-drops flagged:           {n_flagged}"
          f"  ({100*n_flagged/restricted_hops:.1f}% of restricted hops)"
          if restricted_hops else "  (no restricted hops)")
    print(f"  scorable (parked embedded):   {len(scorable)}")
    print(f"  parked edge BETTER than got:  {len(better)}"
          f"  ({100*len(better)/len(scorable):.1f}% of scorable)"
          if scorable else "  scorable: 0")
    # Per-shape frequency.
    from collections import Counter
    by_shape = Counter(x["shape"] for x in flagged)
    if by_shape:
        print("  by shape:", dict(by_shape))


if __name__ == "__main__":
    main()