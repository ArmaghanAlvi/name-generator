"""
Rank-quality probe for the sense dropdown.

Scores an ordering variant against the hand-labeled gold slate
(scripts/eval/dropdown_gold.py) on top-1 accuracy, top-3 accuracy, and MRR,
overall and per sense-count band.

Usage:
    cd backend
    python -m scripts.eval.dropdown_rank_probe --out scripts/eval/dropdown_baseline.json

Reads candidates through fetch_sense_candidates, i.e. the same path the live
dropdown uses. A variant that wins here wins in the product.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Iterable

from app.db.session import SessionLocal
from app.services.dropdown_ranker import collapse_ranked
from app.services.sense_lookup import SenseCandidate, fetch_sense_candidates
from app.services.dropdown_ranker import RankWeights, rank_candidates
from scripts.eval.dropdown_gold import GOLD, GoldLabel, SLATE
from dataclasses import replace

import json
import os

Variant = Callable[[list[SenseCandidate]], list[SenseCandidate]]

_UNPINNED = 10**9

_YIELD_PATH = "scripts/eval/dropdown_yield.json"

# --- variants -------------------------------------------------------------

def _current_order_key(
    candidate: SenseCandidate,
    *,
    use_selection_counts: bool,
) -> tuple[int, int, int, int]:
    """Mirrors the ORDER BY in fetch_sense_candidates exactly."""
    pinned = (
        candidate.pinned_rank
        if candidate.pinned_rank is not None
        else _UNPINNED
    )
    selections = candidate.selection_count if use_selection_counts else 0

    return (
        pinned,
        -selections,
        candidate.sense.source_order,
        candidate.sense.sense_index,
    )


def variant_current(candidates: list[SenseCandidate]) -> list[SenseCandidate]:
    return sorted(
        candidates,
        key=lambda c: _current_order_key(c, use_selection_counts=True),
    )


def variant_current_intrinsic(
    candidates: list[SenseCandidate],
) -> list[SenseCandidate]:
    return sorted(
        candidates,
        key=lambda c: _current_order_key(c, use_selection_counts=False),
    )


# --- metrics (pure; unit-tested) ------------------------------------------

def rank_of(ordered_sense_ids: list[int], target: int) -> int | None:
    """1-indexed rank, or None if absent."""
    try:
        return ordered_sense_ids.index(target) + 1
    except ValueError:
        return None


def reciprocal_rank(ordered_sense_ids: list[int], target: int) -> float:
    rank = rank_of(ordered_sense_ids, target)
    return 0.0 if rank is None else 1.0 / rank


def aggregate(word_results: Iterable[dict]) -> dict:
    rows = list(word_results)
    n = len(rows)

    if n == 0:
        return {"words": 0}

    return {
        "words": n,
        "top1_accuracy": sum(r["top1_hit"] for r in rows) / n,
        "top3_accuracy": sum(r["top3_hit"] for r in rows) / n,
        "acceptable_at_1": sum(r["acceptable_at_1"] for r in rows) / n,
        "mrr": sum(r["reciprocal_rank"] for r in rows) / n,
        "mean_gold_rank": sum(
            r["gold_rank"] for r in rows if r["gold_rank"] is not None
        ) / max(1, sum(1 for r in rows if r["gold_rank"] is not None)),
    }


# --- gold validation ------------------------------------------------------

def validate_gold(candidates_by_word: dict[str, list[SenseCandidate]]) -> None:
    """
    Fail loudly if a label no longer matches the database. Silent drift here
    would poison every number downstream.
    """
    problems: list[str] = []

    for word, label in GOLD.items():
        candidates = candidates_by_word.get(word, [])
        by_id = {c.sense.id: c for c in candidates}

        candidate = by_id.get(label.top1_sense_id)

        if candidate is None:
            problems.append(
                f"{word}: gold sense {label.top1_sense_id} not in candidate set"
            )
            continue

        if candidate.sense.source_locator != label.top1_source_locator:
            problems.append(
                f"{word}: sense {label.top1_sense_id} locator changed "
                f"({candidate.sense.source_locator!r} != "
                f"{label.top1_source_locator!r})"
            )

        missing = label.acceptable_sense_ids - set(by_id)
        if missing:
            problems.append(f"{word}: acceptable ids not in candidates: {missing}")

        if label.top1_sense_id not in (label.acceptable_sense_ids or {label.top1_sense_id}):
            problems.append(f"{word}: top1 not a member of acceptable_sense_ids")

    if problems:
        raise SystemExit("Gold labels are stale:\n  " + "\n  ".join(problems))


# --- runner ---------------------------------------------------------------

def evaluate_variant(
    name: str,
    variant: Variant,
    candidates_by_word: dict[str, list[SenseCandidate]],
    bands: dict[str, str],
    gold: dict[str, GoldLabel] | None = None,
) -> dict:
    labels = GOLD if gold is None else gold
    per_word: list[dict] = []

    for word, label in labels.items():
        ordered = variant(list(candidates_by_word[word]))
        ordered_ids = [c.sense.id for c in ordered]

        gold_rank = rank_of(ordered_ids, label.top1_sense_id)
        acceptable = label.acceptable_sense_ids or {label.top1_sense_id}

        per_word.append(
            {
                "word": word,
                "band": bands[word],
                "ambiguous": label.ambiguous,
                "n_candidates": len(ordered_ids),
                "gold_rank": gold_rank,
                "top1_hit": gold_rank == 1,
                "top3_hit": gold_rank is not None and gold_rank <= 3,
                "acceptable_at_1": ordered_ids[0] in acceptable if ordered_ids else False,
                "reciprocal_rank": reciprocal_rank(ordered_ids, label.top1_sense_id),
                "top_result": ordered_ids[0] if ordered_ids else None,
            }
        )

    unambiguous = [r for r in per_word if not r["ambiguous"]]

    by_band: dict[str, dict] = {}
    for band in sorted({r["band"] for r in per_word}):
        by_band[band] = aggregate(r for r in per_word if r["band"] == band)

    return {
        "variant": name,
        "overall": aggregate(per_word),
        "unambiguous_only": aggregate(unambiguous),
        "by_band": by_band,
        "per_word": per_word,
    }


def evaluate_production_collapsed(
    candidates_by_word: dict[str, list[SenseCandidate]],
    bands: dict[str, str],
) -> dict:
    """
    The shipped pipeline end-to-end: rank under locked RankWeights, then
    collapse. A gold sense absorbed by a duplicate counts as its
    representative (collapse must never turn a hit into a miss); the same
    mapping applies to acceptable_sense_ids.
    """
    ranker = _ranker(RankWeights())
    per_word: list[dict] = []

    for word, label in GOLD.items():
        collapsed = collapse_ranked(ranker(list(candidates_by_word[word])))

        rep_of: dict[int, int] = {}
        for entry in collapsed:
            rep_id = entry.representative.sense.id
            rep_of[rep_id] = rep_id
            for absorbed_id in entry.collapsed_sense_ids:
                rep_of[absorbed_id] = rep_id

        ordered_ids = [entry.representative.sense.id for entry in collapsed]

        gold_target = rep_of.get(label.top1_sense_id, label.top1_sense_id)
        acceptable = {
            rep_of.get(sense_id, sense_id)
            for sense_id in (label.acceptable_sense_ids or {label.top1_sense_id})
        }

        gold_rank = rank_of(ordered_ids, gold_target)

        per_word.append(
            {
                "word": word,
                "band": bands[word],
                "ambiguous": label.ambiguous,
                "n_candidates": len(ordered_ids),
                "n_absorbed": sum(len(e.collapsed_sense_ids) for e in collapsed),
                "gold_rank": gold_rank,
                "top1_hit": gold_rank == 1,
                "top3_hit": gold_rank is not None and gold_rank <= 3,
                "acceptable_at_1": ordered_ids[0] in acceptable if ordered_ids else False,
                "reciprocal_rank": reciprocal_rank(ordered_ids, gold_target),
                "top_result": ordered_ids[0] if ordered_ids else None,
            }
        )

    unambiguous = [r for r in per_word if not r["ambiguous"]]
    by_band = {
        band: aggregate(r for r in per_word if r["band"] == band)
        for band in sorted({r["band"] for r in per_word})
    }

    return {
        "variant": "production_collapsed",
        "overall": aggregate(per_word),
        "unambiguous_only": aggregate(unambiguous),
        "by_band": by_band,
        "per_word": per_word,
    }


def _ranker(weights: RankWeights) -> Variant:
    return lambda candidates: rank_candidates(list(candidates), weights)


def _load_yields() -> dict[int, int] | None:
    if not os.path.exists(_YIELD_PATH):
        return None
    with open(_YIELD_PATH) as handle:
        payload = json.load(handle)
    return {row["sense_id"]: row["yield_count"] for row in payload["rows"]}


def variant_yield_oracle(candidates: list[SenseCandidate]) -> list[SenseCandidate]:
    """
    Ranks purely by measured expansion yield, base order as tiebreak.
    Unshippable by construction — this exists to answer whether yield PREDICTS
    centrality, in the same currency (top1/MRR) as every other signal.
    """
    yields = _load_yields() or {}
    return sorted(
        candidates,
        key=lambda c: (
            -yields.get(c.sense.id, 0),
            c.sense.source_order,
            c.sense.sense_index,
        ),
    )


# The BASE reproduces dictionary order INSIDE the score, so that every other
# signal is measured as a perturbation of it rather than as a replacement for
# it. Scale separation: max primacy magnitude is 0.10 * log1p(110) = 0.471,
# strictly less than the 1.00 etymology step, so etymologies never interleave.
#
# Learned the hard way: with an additive score and a dictionary-order
# tiebreak, ANY nonzero weight overrides dictionary order entirely. There is
# no such thing as a "small nudge" unless the baseline is a term in the score.
BASE = RankWeights(etymology=1.00, primacy=0.10)

# Perturbation magnitudes are sized against a primacy step: moving a sense
# from index 5 to index 1 is worth 0.10 * log1p(4) = 0.161. A weight of ~0.15
# therefore buys roughly four positions of primacy. These are probe values to
# reveal DIRECTION, not proposals.

ABLATIONS: dict[str, RankWeights] = {
    "base":          BASE,
    "gloss_depth":   replace(BASE, gloss_depth=0.15),
    "has_edges":     replace(BASE, has_edges=0.12),
    "edge_count":    replace(BASE, edge_count=0.06),
    "demote_tags":   replace(BASE, hard_demote=0.15, soft_demote=0.06),
    "length_short":  replace(BASE, length=0.06, length_mode="short"),
    "length_banded": replace(BASE, length=0.06, length_mode="banded"),
    "pos_prior":     replace(BASE, pos_prior={"noun": 0.12, "adj": 0.06,
                                              "verb": 0.0, "adv": -0.06}),
}

# 5d: sweep the hard-tier threshold on the dev database (1,138 dev clicks over
# 55 senses). Pick the smallest value that holds acc@1 = 1.000. tier_min_1
# reproduces the ungated hard tier; tier_min_1000000000 disables the tier
# entirely (pure intrinsic).
TIER_SWEEP: dict[str, RankWeights] = {
    f"tier_min_{m}": replace(RankWeights(), selection_tier_min=m)
    for m in (1, 3, 5, 10, 10**9)
}

VARIANTS: dict[str, Variant] = {
    "current": variant_current,
    "current_intrinsic": variant_current_intrinsic,
    "yield_oracle": variant_yield_oracle,
    "production": _ranker(RankWeights()),
    **{f"ablate_{name}": _ranker(w) for name, w in ABLATIONS.items()},
    **{name: _ranker(w) for name, w in TIER_SWEEP.items()},
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None, help="write JSON report here")
    args = parser.parse_args()

    if not GOLD:
        raise SystemExit("GOLD is empty — label the slate first.")

    bands = dict(SLATE)

    with SessionLocal() as db:
        candidates_by_word = {
            word: fetch_sense_candidates(
                db,
                query=word,
                language_code="en",
                limit=500,
                with_relations=True,
            )
            for word, _band in SLATE
        }

        validate_gold(candidates_by_word)

        report = {
            "slate_size": len(GOLD),
            "variants": [
                evaluate_variant(name, variant, candidates_by_word, bands)
                for name, variant in VARIANTS.items()
            ],
        }

        report["variants"].append(
            evaluate_production_collapsed(candidates_by_word, bands)
        )

    for variant_report in report["variants"]:
        overall = variant_report["overall"]
        print(
            f"{variant_report['variant']:<20} "
            f"top1={overall['top1_accuracy']:.3f}  "
            f"top3={overall['top3_accuracy']:.3f}  "
            f"mrr={overall['mrr']:.3f}  "
            f"mean_gold_rank={overall['mean_gold_rank']:.1f}"
        )

    if args.out:
        with open(args.out, "w") as handle:
            json.dump(report, handle, indent=2)
        print(f"\nwrote {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())