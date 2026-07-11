"""
Centrality ranking for the sense dropdown.

Objective: everyday-centrality. "If someone said this word aloud with no
context, which listed meaning would a fluent speaker assume?" This is NOT
name-worthiness and NOT query-relevance.

Deliberately independent of app/services/sense_reranker.py, which serves the
expansion path, scores a different objective (query-relevance), and sits
inside a locked eval baseline. Nothing here imports from there, or vice versa.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.services.sense_display import sense_display_for
from app.services.sense_lookup import SenseCandidate
from app.utils.text import normalize_text

from sqlalchemy import inspect as sa_inspect

_UNPINNED = 10**9

_SYNONYM_RELATIONS = frozenset({"synonym", "near_synonym"})

_HARD_DEMOTE_TAGS = frozenset({
    "rare", "uncommon", "figuratively", "humorous", "poetic", "literary",
    "neologism", "euphemistic", "in-compounds", "attributive", "relational",
})

_SOFT_DEMOTE_TAGS = frozenset({
    "informal", "colloquial", "Internet",
    "US", "UK", "Scotland", "Ireland", "Australia", "Canada",
    "India", "New-Zealand", "South-Africa", "Philippines",
    "Northern-England",
})

# Hard tier: senses with genuine usage outrank all intrinsic signals. This is a
# deliberate product decision -- as the user base grows, popular senses should
# dominate. The threshold prevents a single stray click from doing the same:
# measured, `current` (ungated tier, 1,138 dev clicks over 55 senses) scores
# acc@1 = 0.929 vs 1.000 intrinsic -- one word surfaces an indefensible sense.
SELECTION_TIER_MIN = 5

@dataclass(frozen=True)
class RankSignals:
    sense_index: int          # 1-based, within its lexeme
    etymology_rank: int       # 0-based, within this word's candidate set
    gloss_depth: int          # len(group_path); 0 for a top-level sense
    definition_tokens: int
    synonym_edges: int
    hard_demote_tags: int
    soft_demote_tags: int
    part_of_speech: str
    selection_count: int

    @property
    def has_synonym_edges(self) -> bool:
        return self.synonym_edges > 0


@dataclass(frozen=True)
class RankWeights:
    """
    Locked 2026-07-xx. Evidence: scripts/eval/dropdown_ablation.json,
    scripts/eval/dropdown_tuning.json.

    Result: acc@1 = 1.000 (all 14 slate words surface a defensible sense),
    top1 = 0.571 unchanged, mean_gold_rank 8.2 -> 6.3 in-sample.
    CAVEAT: 96% of that rank gain is one word (`draw`, 87 -> 61). LOO-validated
    gain is +0.14. Both surviving signals are justified a priori and never
    regressed a word, but the slate has only one XL-band word deep enough for
    them to express. Add `run` and `cut` to the slate before retuning.
    """

    # --- base: dictionary order, expressed inside the score -----------------
    # Scale-separated so etymologies never interleave:
    # max primacy = 0.10 * log1p(110) = 0.471 < 1.00.
    etymology: float = 1.00
    primacy: float = 0.10

    # --- selected signals ---------------------------------------------------
    # demote_tags: selected in 14/14 LOO folds. mrr 0.672 -> 0.678, rank -0.7.
    #   Magnitude is draw-sensitive (0.08 without draw); 0.25 is the grid
    #   ceiling -- do NOT widen the grid until the slate has more XL words.
    hard_demote: float = 0.25
    soft_demote: float = 0.10
    # gloss_depth: rank 7.5 -> 6.3, mrr flat. Selected in 13/14 folds, but all
    #   13 contain `draw`; absent from the draw-held-out fold. Evidence base is
    #   n=1. Kept because Wiktionary's gloss nesting IS a derived-sub-sense
    #   marker (a priori), it never regressed a word, and 0.08 is the SMALLEST
    #   grid value -- a gentle prior, not a tuned lever.
    gloss_depth: float = 0.08

    # --- rejected; do not re-add without new evidence ------------------------
    # has_edges / edge_count: confounded with primacy. In all 6 top-1 misses
    #   the incumbent has MORE edges than gold (strength 24v0, draw 72v0,
    #   fire/light 17v0). Bit-identical to base even at 3x weight.
    has_edges: float = 0.0
    edge_count: float = 0.0
    # length: REJECTED. Both modes cost 5 words of acc@1 (1.000 -> 0.643) and
    #   4 words of top-1, at a weight below one primacy step. The original
    #   short-definition hypothesis is disconfirmed, not merely unsupported.
    length: float = 0.0
    length_mode: str = "off"
    # pos_prior: etymology dominance (1.00) structurally blocks cross-etymology
    #   POS effects; same-etymology conflicts on this slate already have gold at
    #   sense_index 1. Bit-identical to base at 2x weight.
    pos_prior: dict[str, float] = field(default_factory=dict)
    # selection (bonus form): superseded by the hard tier below. See 5d.
    selection: float = 0.0

    # --- hard tier (product decision, 5d) -----------------------------------
    selection_tier_min: int = SELECTION_TIER_MIN


def _etymology_ranks(candidates: list[SenseCandidate]) -> dict[int, int]:
    """
    Map lexeme_id -> 0-based rank by source_order within THIS word's candidates.

    source_order is a global integer; comparing it across words is meaningless.
    Normalizing within the candidate set makes the signal scale-free.
    """
    distinct = sorted({(c.sense.source_order, c.lexeme.id) for c in candidates})
    return {lexeme_id: rank for rank, (_order, lexeme_id) in enumerate(distinct)}


def extract_signals(
    candidate: SenseCandidate,
    etymology_ranks: dict[int, int],
) -> RankSignals:
    sense = candidate.sense
    display = sense_display_for(sense, candidate.override)

    tags = {t for t in (sense.raw_tags or []) if isinstance(t, str)}

    # Edge counts are probe-only: no shipped weight uses them (has_edges and
    # edge_count were rejected -- confounded with primacy). Reading
    # sense.relations on a non-eager-loaded Sense would fire one query per
    # candidate (111 for `run`), so only count when already loaded.
    if "relations" in sa_inspect(sense).unloaded:
        edges = 0
    else:
        edges = sum(
            1
            for relation in sense.relations
            if relation.relation_type in _SYNONYM_RELATIONS
        )

    return RankSignals(
        sense_index=sense.sense_index,
        etymology_rank=etymology_ranks[candidate.lexeme.id],
        gloss_depth=len(display.group_path),
        definition_tokens=len(normalize_text(display.definition).split()),
        synonym_edges=edges,
        hard_demote_tags=len(tags & _HARD_DEMOTE_TAGS),
        soft_demote_tags=len(tags & _SOFT_DEMOTE_TAGS),
        part_of_speech=candidate.lexeme.part_of_speech,
        selection_count=candidate.selection_count,
    )


def _length_term(tokens: int, weight: float, mode: str) -> float:
    if weight == 0.0 or mode == "off":
        return 0.0

    if mode == "short":
        # Monotonic: shorter is better. The naive hypothesis.
        return -weight * math.log1p(max(0, tokens - 4))

    if mode == "banded":
        # Peak at 4-12 content tokens; penalize both very short (low-content
        # glosses, the qasgiq/jigha failure mode) and very long (niche senses
        # accumulating technical qualifiers).
        if 4 <= tokens <= 12:
            return 0.0
        distance = 4 - tokens if tokens < 4 else tokens - 12
        return -weight * math.log1p(distance)

    raise ValueError(f"unknown length_mode: {mode!r}")


def score(signals: RankSignals, weights: RankWeights) -> float:
    total = 0.0

    total -= weights.primacy * math.log1p(max(0, signals.sense_index - 1))
    total -= weights.etymology * signals.etymology_rank
    total -= weights.gloss_depth * signals.gloss_depth
    total -= weights.hard_demote * signals.hard_demote_tags
    total -= weights.soft_demote * signals.soft_demote_tags

    if signals.has_synonym_edges:
        total += weights.has_edges
    total += weights.edge_count * math.log1p(signals.synonym_edges)

    total += _length_term(signals.definition_tokens, weights.length, weights.length_mode)
    total += weights.selection * math.log1p(signals.selection_count)
    total += weights.pos_prior.get(signals.part_of_speech, 0.0)

    return total


def _selection_tier(candidate: SenseCandidate, minimum: int) -> int:
    count = candidate.selection_count
    return count if count >= minimum else 0


def rank_candidates(
    candidates: list[SenseCandidate],
    weights: RankWeights,
) -> list[SenseCandidate]:
    """
    Precedence:
      1. pinned_rank (admin override) -- absolute.
      2. selection_count, IF at or above `selection_tier_min` -- a hard tier.
         Product decision (5d): real popularity outranks intrinsic signals.
      3. intrinsic score, descending.
      4. dictionary order (source_order, sense_index) -- deterministic tiebreak.

    Note: in production today, and for all 19 unloaded languages, tier 2 is
    empty -- selection_count is zero everywhere. The intrinsic score is what
    ships. Any probe number computed with tier 2 active on the dev database is
    contaminated by the developer's own clicks; read `current_intrinsic`.
    """
    if not candidates:
        return []

    etymology_ranks = _etymology_ranks(candidates)

    scored = [
        (candidate, score(extract_signals(candidate, etymology_ranks), weights))
        for candidate in candidates
    ]

    return [
        candidate
        for candidate, _score in sorted(
            scored,
            key=lambda pair: (
                pair[0].pinned_rank if pair[0].pinned_rank is not None else _UNPINNED,
                -_selection_tier(pair[0], weights.selection_tier_min),
                -pair[1],
                pair[0].sense.source_order,
                pair[0].sense.sense_index,
            ),
        )
    ]