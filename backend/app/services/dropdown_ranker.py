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
    All zero => the score is flat and ordering falls back to the tiebreak,
    which reproduces `current_intrinsic`. Every non-zero default below must
    be justified by a probe result before it ships.
    """
    primacy: float = 0.0            # * log1p(sense_index - 1), subtracted
    etymology: float = 0.0          # * etymology_rank, subtracted
    gloss_depth: float = 0.0        # * gloss_depth, subtracted
    has_edges: float = 0.0          # flat bonus
    edge_count: float = 0.0         # * log1p(synonym_edges)
    hard_demote: float = 0.0        # * hard_demote_tags, subtracted
    soft_demote: float = 0.0        # * soft_demote_tags, subtracted
    length: float = 0.0             # see `length_mode`
    length_mode: str = "off"        # "off" | "short" | "banded"
    selection: float = 0.0          # * log1p(selection_count)
    pos_prior: dict[str, float] = field(default_factory=dict)


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


def rank_candidates(
    candidates: list[SenseCandidate],
    weights: RankWeights,
) -> list[SenseCandidate]:
    """
    Precedence:
      1. pinned_rank (admin override) — absolute.
      2. intrinsic score, descending.
      3. dictionary order (source_order, sense_index) — deterministic tiebreak.

    Note selection_count enters via `weights.selection` as a BOUNDED bonus,
    not as a hard sort tier. Under the old hard tier, a single stray click
    outranked every intrinsic signal. Step 3 tests both.
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
                -pair[1],
                pair[0].sense.source_order,
                pair[0].sense.sense_index,
            ),
        )
    ]