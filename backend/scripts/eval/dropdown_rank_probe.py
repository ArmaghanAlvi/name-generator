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
from app.services.sense_lookup import SenseCandidate, fetch_sense_candidates
from scripts.eval.dropdown_gold import GOLD, SLATE


Variant = Callable[[list[SenseCandidate]], list[SenseCandidate]]

_UNPINNED = 10**9


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
) -> dict:
    per_word: list[dict] = []

    for word, label in GOLD.items():
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


VARIANTS: dict[str, Variant] = {
    "current": variant_current,
    "current_intrinsic": variant_current_intrinsic,
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