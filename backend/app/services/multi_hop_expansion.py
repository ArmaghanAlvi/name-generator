"""
Multi-hop expansion engine.

Orchestrates repeated calls to expand() to walk outward from a user-selected
sense, carrying each hit's sense forward (sense continuity) and restricting
edge-collection to the hopped sense at depth >= 2 (the validated fix). Produces
a flat, deduped, ranked list of HopNodes with hop paths and edge provenance.

Pipeline:
  - Traversal (Stage 1): BFS by depth, width children per node, depth cap.
    Dedup by displayed word with shortest-path ownership; dead branches
    self-prune (a fully-converged node yields no fresh children, so it never
    reaches the next frontier).
  - Ranking (Stage 2): each node scored by anchored_score — a gentle blend of
    parent-relative score and similarity to the ORIGIN query vector, minus a
    mild per-hop decay, so drift is ordered tight-to-wild without being
    suppressed. No hard prune (origin-distance can't cleanly isolate
    same-register false friends like bravura; see roadmap Stage 2 deferral).
  - Cleanliness (Stage 3): cross-hop family throttle soft-penalizes same-family
    survivors (by shared-prefix same_family) that the exact-match `seen` set
    can't catch, so one morphological root can't crowd the top.

Output is ordered by anchored_score, root pinned first.
"""


from __future__ import annotations

from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.semantic import Sense, SenseEmbedding
from app.services.expansion import expand
from app.services.morphology import same_family
from app.services.vector_sense_search import (
    get_selected_senses,
    display_word_key_for_sense,
)
from app.utils.text import normalize_text


# --- Stage 2 ranking knobs (tune in Roadmap Stage 7) ---
# Gentle origin pull: parent-relative quality still dominates; origin nudges.
ALPHA_ORIGIN = 0.35
# Mild per-hop decay so hop-1 outranks hop-3 all else equal (leap-size order).
DECAY_PER_HOP = 0.02
# Cross-hop family throttle: each successive same-family member (by descending
# anchored_score) is penalized this much * its rank within the family, so one
# morphological root (lumin-, bright-) can't monopolize the result list.
FAMILY_PENALTY_STEP = 0.03


@dataclass(frozen=True)
class HopNode:
    sense: Sense
    score: float            # raw per-hop score from expand() (parent-relative)
    depth: int              # 0 = root, 1 = first hop, ...
    provenance: str         # selected | kaikki_synonym | oewn_synonym | oewn_near_synonym | vector
    reason: str             # raw reason from the underlying SenseSearchHit (traceability)
    path: tuple[str, ...]   # display lemmas, root-first, inclusive of this node
    origin_sim: float = 1.0       # cosine to the origin query vector (Stage 2)
    anchored_score: float = 1.0   # blended (origin+parent), depth-decayed rank (Stage 2)



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


def _build_origin_query_vector(root_sense: Sense) -> list[float]:
    """
    The vector that defines "what the user searched" — the enriched query
    built from the ROOT sense (lemma + definition + its synonyms), embedded
    once. Identical construction to expand()'s root query, so origin
    similarity is on the same scale as the scores already in the tree.
    """
    from app.services.embedding_provider import embed_query
    from app.services.vector_sense_search import (
        build_query_text_from_selected_senses,
    )
    return embed_query(build_query_text_from_selected_senses([root_sense]))


def _origin_similarities(
    db: Session,
    sense_ids: list[int],
    origin_vector: list[float],
) -> dict[int, float]:
    """
    Cosine similarity (1 - distance) of each sense's embedding to the origin
    vector, batched in one query. Senses without an embedding are absent from
    the result (callers default them to 0.0); in practice every node here is
    embedded, since the resolver only surfaces embedded senses.
    """
    if not sense_ids:
        return {}
    rows = db.execute(
        select(
            SenseEmbedding.sense_id,
            SenseEmbedding.embedding.cosine_distance(origin_vector).label("d"),
        ).where(SenseEmbedding.sense_id.in_(sense_ids))
    ).all()
    return {sid: max(0.0, 1.0 - float(d)) for sid, d in rows}


def _anchored_score(local_score: float, origin_sim: float, depth: int) -> float:
    """
    Blend parent-relative quality with origin similarity, then apply a mild
    per-hop decay. ALPHA_ORIGIN is small so this NUDGES toward the origin
    rather than collapsing drift back to a strict origin rank — drift is the
    feature; this just orders it.
    """
    blended = (1.0 - ALPHA_ORIGIN) * local_score + ALPHA_ORIGIN * origin_sim
    return max(0.0, blended - DECAY_PER_HOP * depth)


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


def _apply_cross_hop_family_throttle(nodes: list[HopNode]) -> list[HopNode]:
    """
    Soft-throttle morphological families across the whole traversal.

    The `seen` set only removes exact-duplicate lemmas; distinct same-family
    survivors (luminance / luminousness / luminosity) slip through in separate
    expand() calls. This pass groups them by same_family, keeps the strongest
    member penalty-free, and penalizes each successive member by descending
    anchored_score. Never penalizes the root (depth 0).

    Returns nodes re-scored (anchored_score adjusted) but NOT re-sorted — the
    caller re-sorts, so this composes with leap-size ordering.
    """
    root = [n for n in nodes if n.depth == 0]
    expanded = [n for n in nodes if n.depth > 0]
    expanded.sort(key=lambda n: n.anchored_score, reverse=True)

    kept_lemmas: list[str] = []
    out: list[HopNode] = []
    for n in expanded:
        lemma = normalize_text(n.sense.lexeme.lemma)
        family_count = sum(1 for k in kept_lemmas if same_family(lemma, k))
        penalty = FAMILY_PENALTY_STEP * family_count
        if penalty:
            out.append(replace(
                n,
                anchored_score=max(0.0, n.anchored_score - penalty),
                reason=n.reason + f" | xhop-family -{penalty:.2f}",
            ))
        else:
            out.append(n)
        kept_lemmas.append(lemma)

    return root + out


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

    origin_vector = _build_origin_query_vector(root_sense)

    seen: set[str] = {display_word_key_for_sense(root_sense)}
    all_nodes: list[HopNode] = [root_node]
    frontier: list[HopNode] = [root_node]

    for level in range(1, depth + 1):
        # level 1 expands the ROOT (user-selected) -> unrestricted.
        # level >= 2 expands HOPPED near-synonyms -> restricted.
        restrict = level >= 2

        # 1) Collect every candidate child this level (raw, parent-relative).
        candidates: list[HopNode] = []
        for parent in frontier:
            candidates.extend(_expand_one_node(
                db, parent,
                width=width, restrict=restrict,
                target_language=target_language,
                min_length=min_length, max_length=max_length,
            ))
        if not candidates:
            break

        # 2) Attach origin similarity + anchored score to each candidate.
        origin_sims = _origin_similarities(
            db, [c.sense.id for c in candidates], origin_vector,
        )
        scored: list[HopNode] = []
        for c in candidates:
            o = origin_sims.get(c.sense.id, 0.0)
            scored.append(replace(
                c,
                origin_sim=o,
                anchored_score=_anchored_score(c.score, o, c.depth),
            ))

        # 3) Dedup within the level by anchored_score. Earlier (shorter) paths
        #    already own their words via `seen`; here we pick, among same-level
        #    rivals for a new word, the one closest to the origin.
        level_best: dict[str, HopNode] = {}
        for child in scored:
            key = display_word_key_for_sense(child.sense)
            if key in seen:
                continue
            incumbent = level_best.get(key)
            if incumbent is None or child.anchored_score > incumbent.anchored_score:
                level_best[key] = child

        if not level_best:
            break

        # 4) Commit this level's winners as results.
        committed = list(level_best.values())
        for child in committed:
            seen.add(display_word_key_for_sense(child.sense))
            all_nodes.append(child)

        # 5) Next frontier = committed winners (Step 3 prunes this).
        frontier = committed

    # Cross-hop family throttle (Stage 3): penalize same-family survivors that
    # slipped past the exact-match `seen` set, so one morphological root can't
    # crowd the top. Adjusts anchored_score; does not re-sort.
    all_nodes = _apply_cross_hop_family_throttle(all_nodes)

    # Leap-size ordering: root pinned first, then by anchored_score (gentle
    # origin pull + per-hop decay), so tight drift surfaces before wild drift.
    root_out = next(n for n in all_nodes if n.depth == 0)
    rest = sorted((n for n in all_nodes if n.depth > 0),
                  key=lambda n: n.anchored_score, reverse=True)
    return [root_out] + rest