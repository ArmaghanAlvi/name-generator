"""
Forward-selects signals, coarse-grids their weights, and reports leave-one-out
accuracy so we can see whether the result generalizes or memorized the slate.

Objective: MRR, with top-1 as tiebreak. A candidate signal is REJECTED if it
drops any word from top-3 to outside, regardless of aggregate improvement --
a signal that trades one word for another has no evidence behind it at n=14.

Usage:
    cd backend
    python -m scripts.eval.dropdown_tune --out scripts/eval/dropdown_tuning.json
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace

from app.db.session import SessionLocal
from app.services.dropdown_ranker import RankWeights, rank_candidates
from app.services.sense_lookup import fetch_sense_candidates
from scripts.eval.dropdown_gold import GOLD, SLATE
from scripts.eval.dropdown_rank_probe import evaluate_variant, validate_gold

BASE = RankWeights(etymology=1.00, primacy=0.10)

MIN_MRR_IMPROVEMENT = 0.003       # was 0.01 -- nothing on this slate clears it
MIN_RANK_IMPROVEMENT = 0.5        # positions of mean_gold_rank

# Signals excluded, with reasons, so this doesn't look like an oversight:
#
#   has_edges, edge_count -- verified confounded with primacy: in all 6 top-1
#     misses the incumbent has MORE edges than gold (strength 24v0, draw 72v0,
#     fire/light 17v0). Edge count restates dictionary order rather than
#     correcting it. Bit-identical to base even at 3x weight.
#   pos_prior -- etymology dominance (weight 1.00) structurally blocks
#     cross-etymology POS effects; same-etymology POS conflicts on this slate
#     already have gold at sense_index 1. Bit-identical to base at 2x weight.
#   yield -- measured (dropdown_yield.json): ANTI-correlated with centrality
#     (gold at 19th percentile of yield, max in 0/14 words). Also unshippable:
#     387s for 389 candidates.
#   length (both modes) -- rejected. Costs 4 words of top-1 at a weight well
#     below one primacy step. The original short-definition hypothesis is
#     disconfirmed, not merely unsupported.
#   selection -- EXCLUDED from forward selection. selection_count is 1,138 dev
#     clicks across 55 senses, made while choosing the senses later labeled as
#     gold. It is a near-copy of the answer key, and LOO cannot detect this
#     (the leak is in the FEATURE, not the label -- held-out words carry their
#     own selection counts into every fold). It is also identically zero for
#     new users and for all 19 unloaded languages. Decided separately in 5d as
#     a product question, not a tuned weight.
CANDIDATE_SIGNALS: dict[str, list[dict]] = {
    "gloss_depth": [{"gloss_depth": v} for v in (0.08, 0.15, 0.25, 0.40)],
    "demote_tags": [{"hard_demote": v, "soft_demote": v / 2.5}
                    for v in (0.08, 0.15, 0.25)],
}


def _score(weights: RankWeights, candidates_by_word, bands, gold) -> dict:
    report = evaluate_variant(
        "probe",
        lambda cands: rank_candidates(list(cands), weights),
        candidates_by_word,
        bands,
        gold=gold,
    )
    return report["overall"] | {"per_word": report["per_word"]}


def _top3_words(result: dict) -> set[str]:
    return {r["word"] for r in result["per_word"] if r["top3_hit"]}


def _acceptable_words(result: dict) -> set[str]:
    return {r["word"] for r in result["per_word"] if r["acceptable_at_1"]}


def forward_select(candidates_by_word, bands, gold, verbose=True) -> RankWeights:
    weights: RankWeights = BASE
    current = _score(weights, candidates_by_word, bands, gold)
    remaining = dict(CANDIDATE_SIGNALS)

    while remaining:
        best_name: str | None = None
        best_weights: RankWeights | None = None
        best_result: dict | None = None

        for name, settings in remaining.items():
            for setting in settings:
                trial: RankWeights = replace(weights, **setting)
                result = _score(trial, candidates_by_word, bands, gold)

                # Hard rules: never lose a word from top-3, and never demote a
                # word's top pick out of its acceptable set (protects the
                # acc@1 = 1.000 floor confirmed in Step 3/4 -- see
                # dropdown_ablation.json).
                if not _top3_words(current) <= _top3_words(result):
                    continue
                if not _acceptable_words(current) <= _acceptable_words(result):
                    continue

                # Compare on (mrr, -mean_gold_rank, top1_accuracy). Without the
                # mean_gold_rank term, a signal that ONLY improves mean rank
                # (gloss_depth: mrr/top1 unchanged, rank 8.2 -> 7.0) ties
                # `current` on every trial and is never recognized as "best" --
                # even though the acceptance check below explicitly allows a
                # rank-only win. Found while reviewing this file: gloss_depth,
                # the one signal validated as a real win, was silently
                # unselectable before this fix.
                candidate_key = (
                    result["mrr"], -result["mean_gold_rank"], result["top1_accuracy"],
                )
                baseline_key = (
                    (best_result["mrr"], -best_result["mean_gold_rank"],
                     best_result["top1_accuracy"])
                    if best_result else
                    (current["mrr"], -current["mean_gold_rank"], current["top1_accuracy"])
                )

                if candidate_key > baseline_key:
                    best_name, best_weights, best_result = name, trial, result

        if best_result is None:
            break

        # best_name / best_weights are always set together with best_result --
        # tell the type checker what the runtime already guarantees.
        assert best_name is not None and best_weights is not None

        mrr_gain = best_result["mrr"] - current["mrr"]
        rank_gain = current["mean_gold_rank"] - best_result["mean_gold_rank"]

        if mrr_gain < MIN_MRR_IMPROVEMENT and rank_gain < MIN_RANK_IMPROVEMENT:
            break

        if verbose:
            print(f"  + {best_name:<14} mrr {current['mrr']:.3f} -> "
                  f"{best_result['mrr']:.3f}  "
                  f"rank {current['mean_gold_rank']:.1f} -> "
                  f"{best_result['mean_gold_rank']:.1f}  "
                  f"acc@1 {best_result['acceptable_at_1']:.3f}")

        weights, current = best_weights, best_result
        remaining.pop(best_name)

    return weights


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="scripts/eval/dropdown_tuning.json")
    args = parser.parse_args()

    bands = dict(SLATE)

    with SessionLocal() as db:
        candidates_by_word = {
            word: fetch_sense_candidates(db, query=word, language_code="en",
                                         limit=500, with_relations=True)
            for word, _band in SLATE
        }

        validate_gold(candidates_by_word)

        print("Forward selection (in-sample):")
        final = forward_select(candidates_by_word, bands, GOLD)
        in_sample = _score(final, candidates_by_word, bands, GOLD)

        print("\nLeave-one-out:")
        loo_hits = 0
        loo_acceptable_hits = 0
        loo_rank_deltas: list[float] = []
        loo_detail = []

        for held_out in GOLD:
            train = {w: label for w, label in GOLD.items() if w != held_out}
            tuned = forward_select(candidates_by_word, bands, train, verbose=False)

            held = {held_out: GOLD[held_out]}
            test = _score(tuned, candidates_by_word, bands, held)
            base = _score(BASE, candidates_by_word, bands, held)

            # The real generalization question on this slate: do weights tuned
            # WITHOUT this word still improve ITS rank? top-1 is constant across
            # all weight settings here, so a top-1 gap of 0.000 is arithmetic,
            # not evidence.
            rank_delta = base["mean_gold_rank"] - test["mean_gold_rank"]
            loo_rank_deltas.append(rank_delta)

            hit = test["top1_accuracy"] == 1.0
            acceptable_hit = test["acceptable_at_1"] == 1.0
            loo_hits += hit
            loo_acceptable_hits += acceptable_hit

            loo_detail.append({
                "word": held_out,
                "top1_hit": hit,
                "acceptable_hit": acceptable_hit,
                "base_rank": base["mean_gold_rank"],
                "tuned_rank": test["mean_gold_rank"],
                "rank_delta": rank_delta,
                "weights": asdict(tuned),
            })
            print(f"  {held_out:<10} rank {base['mean_gold_rank']:>5.1f} -> "
                  f"{test['mean_gold_rank']:>5.1f}  (Δ{rank_delta:+.1f})  "
                  f"acc@1={'hit' if acceptable_hit else 'MISS'}")

    loo_top1 = loo_hits / len(GOLD)
    loo_acceptable = loo_acceptable_hits / len(GOLD)
    mean_rank_delta = sum(loo_rank_deltas) / len(loo_rank_deltas)
    regressions = [d["word"] for d in loo_detail if d["rank_delta"] < 0]

    # Retained for the record, but NOT a meaningful overfit test on this slate:
    # no weight setting moves top-1 at all, so this difference is arithmetically
    # forced to 0.000 whether or not the model generalizes. The real
    # generalization signal is `mean_rank_delta` below.
    gap = in_sample["top1_accuracy"] - loo_top1

    print(f"\nin-sample acc@1     = {in_sample['acceptable_at_1']:.3f}")
    print(f"in-sample top1      = {in_sample['top1_accuracy']:.3f}")
    print(f"in-sample rank      = {in_sample['mean_gold_rank']:.1f}")
    print(f"LOO   acc@1         = {loo_acceptable:.3f}")
    print(f"LOO   top1          = {loo_top1:.3f}  (degenerate here -- see comment)")
    print(f"LOO   mean Δrank    = {mean_rank_delta:+.2f}  "
          f"(positive = held-out words improved)")
    print(f"LOO   regressions   = {regressions or 'none'}")

    with open(args.out, "w") as handle:
        json.dump({
            "final_weights": asdict(final),
            "in_sample": {k: v for k, v in in_sample.items() if k != "per_word"},
            "per_word": in_sample["per_word"],
            "loo_top1": loo_top1,
            "loo_acceptable_at_1": loo_acceptable,
            "loo_mean_rank_delta": mean_rank_delta,
            "loo_regressions": regressions,
            "loo_gap": gap,
            "loo_detail": loo_detail,
        }, handle, indent=2)

    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())