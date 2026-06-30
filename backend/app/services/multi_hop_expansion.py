"""
Multi-hop expansion engine.

Orchestrates repeated calls to expand() to walk outward from a user-selected
sense, carrying each hit's sense forward (sense continuity) and restricting
edge-collection to the hopped sense at depth >= 2 (the validated fix). Produces
a flat, deduped list of HopNodes with hop paths and edge provenance.

Stage 1 is STRUCTURE ONLY: no origin-anchored re-scoring, decay, or pruning
(those are Stage 2). Scores here are the raw per-hop scores expand() returns,
i.e. similarity to the IMMEDIATE parent, not the origin.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.semantic import Sense
from app.services.expansion import expand
from app.services.vector_sense_search import (
    get_selected_senses,
    display_word_key_for_sense,
)


@dataclass(frozen=True)
class HopNode:
    sense: Sense
    score: float            # raw per-hop score from expand() (parent-relative)
    depth: int              # 0 = root, 1 = first hop, ...
    provenance: str         # selected | kaikki_synonym | oewn_synonym | oewn_near_synonym | vector
    reason: str             # raw reason from the underlying SenseSearchHit (traceability)
    path: tuple[str, ...]   # display lemmas, root-first, inclusive of this node



def _classify_provenance(reason: str) -> str:
    """
    Map expand()'s free-text `reason` to a stable provenance label.

    expand() reasons observed:
      "user_selected_meaning"
      "kaikki_synonym" | "oewn_synonym" | "oewn_near_synonym"
      "pgvector_similarity_auto_reranked: vector=0.882 | ..."
    Any of these may have " | family-penalty -0.03" appended by the throttle,
    so we split on " | " and read the head segment.
    """
    head = reason.split(" | ")[0]
    if head == "user_selected_meaning":
        return "selected"
    if head.startswith("pgvector_similarity"):
        return "vector"
    return head  # one of the edge-tier labels


def _expand_one_node(
    db: Session,
    node: HopNode,
    *,
    width: int,
    restrict: bool,
    target_language: str | None,
    min_length: int,
    max_length: int,
) -> list[HopNode]:
    """
    Expand a single node into up to `width` child HopNodes.

    Sense continuity: expands node.sense.id (the displayed sense), never a
    re-resolved lemma. Restriction: pass restrict_edges_to_selected=restrict
    so hops (depth >= 2) only collect the hopped sense's own edges.
    """
    hits = expand(
        db,
        selected_sense_ids=[node.sense.id],
        expansion_count=width,
        target_language=target_language,
        min_length=min_length,
        max_length=max_length,
        restrict_edges_to_selected=restrict,
    )
    children: list[HopNode] = []
    for h in hits:
        if h.match_type != "expanded":
            continue
        children.append(
            HopNode(
                sense=h.sense,
                score=h.score,
                depth=node.depth + 1,
                provenance=_classify_provenance(h.reason),
                reason=h.reason,
                path=node.path + (h.sense.lexeme.lemma,),
            )
        )
    return children


def multi_hop_expand(
    db: Session,
    *,
    root_sense_id: int,
    width: int,
    depth: int,
    target_language: str | None = None,
    min_length: int = 0,
    max_length: int = 30,
) -> list[HopNode]:
    """
    Walk outward from root_sense_id, fanning out `width` per node for `depth`
    hops. Returns a flat, deduped list of HopNodes (root first, then BFS order).

    width or depth <= 0 returns just the root (matches "0 expansions/0 hops ->
    1 result"). Restriction is OFF for the root expansion (depth-1 level) and ON
    for every hop after (depth >= 2), per the validated depth-scoping rule.
    """
    roots = get_selected_senses(db, sense_ids=[root_sense_id])
    if not roots:
        return []
    root_sense = roots[0]
    root_node = HopNode(
        sense=root_sense,
        score=1.0,
        depth=0,
        provenance="selected",
        reason="user_selected_meaning",
        path=(root_sense.lexeme.lemma,),
    )

    if width <= 0 or depth <= 0:
        return [root_node]

    seen: set[str] = {display_word_key_for_sense(root_sense)}
    all_nodes: list[HopNode] = [root_node]
    frontier: list[HopNode] = [root_node]

    for level in range(1, depth + 1):
        # level 1 expands the ROOT (user-selected) -> unrestricted.
        # level >= 2 expands HOPPED near-synonyms -> restricted.
        restrict = level >= 2

        # Collect the whole level first, then resolve same-level dedup by score
        # (placeholder tiebreak; Stage 2 will key this on origin similarity).
        level_best: dict[str, HopNode] = {}
        for parent in frontier:
            for child in _expand_one_node(
                db, parent,
                width=width, restrict=restrict,
                target_language=target_language,
                min_length=min_length, max_length=max_length,
            ):
                key = display_word_key_for_sense(child.sense)
                if key in seen:
                    continue  # owned by an earlier (shorter) path
                incumbent = level_best.get(key)
                if incumbent is None or child.score > incumbent.score:
                    level_best[key] = child

        if not level_best:
            break

        next_frontier = list(level_best.values())
        for child in next_frontier:
            seen.add(display_word_key_for_sense(child.sense))
            all_nodes.append(child)
        frontier = next_frontier

    return all_nodes