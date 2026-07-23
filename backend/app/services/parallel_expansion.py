"""
Parallel-tree orchestrator (MULTILINGUAL_EXPANSION_MODEL.md 1, 2b, 2c;
Breakdown 4 Steps 1c/1d).

For one user-selected ENGLISH sense: one root per language (root_selection),
one language-scoped tree per root (multi_hop_expand, untouched), a bounded
root-level English pivot for starving Russian trees, and a merged view:
root band first (fixed language order), then round-robin by within-tree
lineage order. Scores are NEVER compared across trees -- rank only.

The English tree is multi_hop_expand on the selected sense itself: the
pre-existing code path, unmodified, called with the same arguments the API
uses today.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.semantic import SenseEmbedding, SenseTranslation
from app.services.expansion import expand
from app.services.multi_hop_expansion import HopNode, multi_hop_expand
from app.services.root_selection import RootCandidate, select_roots

# Interleave language order (Breakdown 4, Step 1d -- recorded decision):
# English first (query language + byte-identical anchor), then all other
# imported languages by ascending language id (== import order, stable and
# deterministic). DERIVED so importing a language adds it to the interleave
# with no code change. Ordering only -- never touches membership or scores.
_language_order_cache: list[str] | None = None


def _language_order(db: Session) -> list[str]:
    global _language_order_cache
    if _language_order_cache is not None:
        return _language_order_cache
    from app.models.generated_name import Language
    from app.models.semantic import Lexeme, Sense

    codes = [
        code for (code,) in db.execute(
            select(Language.code)
            .join(Lexeme, Lexeme.language_id == Language.id)
            .join(Sense, Sense.lexeme_id == Lexeme.id)
            .where(Sense.visibility_status == "visible")
            .group_by(Language.id, Language.code)
            .order_by(Language.id)
        )
    ]
    ordered = (["en"] if "en" in codes else []) + [c for c in codes if c != "en"]
    _language_order_cache = ordered
    return _language_order_cache


# Pivot eligibility (Step 1c) is DERIVED, not a hardcoded set: a language
# pivots iff it has NO within-language wordnet synonym edges -- the exact
# structural reason a graph starves (Russian today; any future no-wordnet
# language automatically). Languages WITH omw/awn edges (ja/ar) are excluded
# by construction. Computed once and cached; the pivot itself is root-level,
# bounded to the depth-1 deficit, one English hop (unchanged).
_WORDNET_PROVENANCES = ("omw-ja", "omw-arb", "awn4")

_pivot_eligible_cache: set[str] | None = None


def _pivot_eligible_languages(db: Session) -> set[str]:
    """Language codes with visible senses but zero wordnet synonym edges.
    English is never eligible (it has oewn edges and is the pivot TARGET,
    never a pivot source)."""
    global _pivot_eligible_cache
    if _pivot_eligible_cache is not None:
        return _pivot_eligible_cache
    from app.models.generated_name import Language
    from app.models.semantic import Lexeme, Sense, SenseRelation

    has_wordnet = {
        code for (code,) in db.execute(
            select(Language.code)
            .join(Lexeme, Lexeme.language_id == Language.id)
            .join(Sense, Sense.lexeme_id == Lexeme.id)
            .join(SenseRelation, SenseRelation.from_sense_id == Sense.id)
            .where(SenseRelation.provenance.in_(_WORDNET_PROVENANCES))
            .distinct()
        )
    }
    all_non_en = {
        code for (code,) in db.execute(
            select(Language.code)
            .join(Lexeme, Lexeme.language_id == Language.id)
            .join(Sense, Sense.lexeme_id == Lexeme.id)
            .where(Language.code != "en",
                   Sense.visibility_status == "visible")
            .distinct()
        )
    }
    _pivot_eligible_cache = all_non_en - has_wordnet
    return _pivot_eligible_cache


@dataclass(frozen=True)
class LanguageTree:
    language_code: str
    root: RootCandidate | None      # None for en (the selected sense IS the root)
    nodes: list[HopNode]            # lineage-ordered; empty if no root
    pivoted_count: int


@dataclass(frozen=True)
class ParallelExpansion:
    trees: dict[str, LanguageTree]
    interleaved: list[HopNode]      # root band, then round-robin


def _pivot_top_up(
    db: Session, *, tree_nodes: list[HopNode], root_node: HopNode,
    language_id: int, need: int, min_length: int, max_length: int,
) -> list[HopNode]:
    """ru-tree rescue: root -> EN equivalent -> EN edge synonyms -> back."""
    if need <= 0:
        return []
    root_lexeme_id = root_node.sense.lexeme_id

    # Reverse link: English senses that translate to this lexeme.
    en_sense_id = db.scalar(
        select(SenseTranslation.sense_id)
        .where(SenseTranslation.target_lexeme_id == root_lexeme_id,
               SenseTranslation.language_id == language_id)
        .order_by(SenseTranslation.sense_id).limit(1)
    )
    if en_sense_id is None:
        return []

    # English synonyms of that sense (edge tiers only -- expand() handles it).
    en_hits = expand(
        db, selected_sense_ids=[en_sense_id], expansion_count=need * 3,
        min_length=0, max_length=30,
    )

    # Forward-translate each English synonym back into this language.
    from app.services.root_selection import _display_sense  # display policy shared
    existing = {n.sense.lexeme.lemma for n in tree_nodes}
    root_vec = db.scalar(select(SenseEmbedding.embedding)
                         .where(SenseEmbedding.sense_id == root_node.sense.id))
    out: list[HopNode] = []
    for h in en_hits:
        if h.match_type != "expanded" or len(out) >= need:
            continue
        tgt_lexeme_id = db.scalar(
            select(SenseTranslation.target_lexeme_id)
            .where(SenseTranslation.sense_id == h.sense.id,
                   SenseTranslation.language_id == language_id,
                   SenseTranslation.target_lexeme_id.isnot(None))
            .limit(1)
        )
        if tgt_lexeme_id is None:
            continue
        disp = _display_sense(db, tgt_lexeme_id)
        if disp is None or disp.lexeme.lemma in existing:
            continue
        sim = 0.0
        if root_vec is not None:
            d = db.scalar(
                select(SenseEmbedding.embedding.cosine_distance(root_vec))
                .where(SenseEmbedding.sense_id == disp.id))
            sim = max(0.0, 1.0 - float(d)) if d is not None else 0.0
        existing.add(disp.lexeme.lemma)
        out.append(HopNode(
            sense=disp, score=sim, depth=1, provenance="pivoted",
            reason=f"pivoted_via_en:{h.sense.lexeme.lemma}",
            path=root_node.path + (disp.lexeme.lemma,),
            path_sense_ids=root_node.path_sense_ids + (disp.id,),
            parent_sense_id=root_node.sense.id,
            origin_sim=sim, anchored_score=sim,
        ))
    return out


# Rungs a rescued root may inherit from a synonym. FALLBACK IS EXCLUDED
# deliberately: a vector-NN root reached THROUGH a synonym is two weak
# inferences stacked, which is exactly the compounding-drift failure the
# model doc rejected in Model 2. Rescue borrows only hard evidence.
_RESCUE_RUNGS = ("corroborated", "primary", "ili")


def _pivot_root_rescue(
    db: Session, *, english_sense_id: int, language_code: str,
    max_synonyms: int = 5,
) -> RootCandidate | None:
    """
    Root-level pivot rescue (Breakdown 4, Step 6 revision).

    When select_root() finds NOTHING for a pivot-eligible language, try the
    English sense's own SYNONYMS as alternative anchors: light -> brightness
    -> свет. The rescued root must be backed by a translation link or shared
    ILI on the synonym (never that synonym's own vector fallback), and must
    STILL clear the original pair's root floor measured against the ORIGINAL
    English sense -- so a synonym that drifted semantically cannot smuggle in
    a distant root.

    Returns a RootCandidate tagged rung='pivoted_root' so a rescued root is
    diagnosable at a glance, exactly like depth-1 'pivoted' nodes.
    """
    from app.services.root_selection import (
        ROOT_RESCUE_FLOORS, _cross_sim, _en_vector, select_root,
    )

    en_vector = _en_vector(db, english_sense_id)
    hits = expand(
        db, selected_sense_ids=[english_sense_id],
        expansion_count=max_synonyms, min_length=0, max_length=30,
    )
    floor = ROOT_RESCUE_FLOORS.get(language_code)

    for h in hits:
        if h.match_type != "expanded":
            continue
        # Edge-backed synonyms only: a vector-reached English synonym is not
        # a trustworthy anchor to pivot a whole tree through.
        if h.reason.split(" | ")[0].startswith("pgvector_similarity"):
            continue
        cand = select_root(
            db, english_sense_id=h.sense.id, language_code=language_code,
        )
        if cand is None or cand.rung not in _RESCUE_RUNGS:
            continue
        # Re-score against the ORIGINAL sense, not the synonym.
        sim = _cross_sim(db, en_vector, cand.sense.id)
        if floor is not None and sim < floor:
            continue
        return RootCandidate(language_code, cand.sense, "pivoted_root", sim)
    return None


def parallel_expand(
    db: Session, *, english_sense_id: int,
    language_codes: list[str] | None = None,
    width: int, depth: int, min_length: int = 0, max_length: int = 30,
) -> ParallelExpansion:
    order = _language_order(db)
    requested = language_codes if language_codes is not None else order
    codes = [c for c in order if c in requested]
    non_en = [c for c in codes if c != "en"]
    roots = select_roots(db, english_sense_id=english_sense_id,
                         language_codes=non_en) if non_en else {}

    trees: dict[str, LanguageTree] = {}
    for code in codes:
        if code == "en":
            nodes = multi_hop_expand(
                db, root_sense_id=english_sense_id, width=width, depth=depth,
                min_length=min_length, max_length=max_length,
            )
            trees[code] = LanguageTree(code, None, nodes, 0)
            continue
        rc = roots.get(code)
        if rc is None and code in _pivot_eligible_languages(db):
            # No root from any ladder rung. For a pivot-eligible (wordnet-less)
            # language, try the English sense's synonyms as alternative anchors
            # before giving up -- these are precisely the languages whose thin
            # translation coverage the pivot exists to rescue.
            rc = _pivot_root_rescue(
                db, english_sense_id=english_sense_id, language_code=code,
            )
        if rc is None:
            trees[code] = LanguageTree(code, None, [], 0)
            continue
        nodes = multi_hop_expand(
            db, root_sense_id=rc.sense.id, width=width, depth=depth,
            min_length=min_length, max_length=max_length,
        )
        pivoted = 0
        if code in _pivot_eligible_languages(db) and nodes:
            depth1 = sum(1 for n in nodes if n.depth == 1)
            extra = _pivot_top_up(
                db, tree_nodes=nodes, root_node=nodes[0],
                language_id=rc.sense.lexeme.language_id,
                need=width - depth1,
                min_length=min_length, max_length=max_length,
            )
            nodes = nodes + extra
            pivoted = len(extra)
        trees[code] = LanguageTree(code, rc, nodes, pivoted)

    # ---- interleave: root band, then round-robin (Step 1d) ----------------
    interleaved: list[HopNode] = []
    rests: dict[str, list[HopNode]] = {}
    for code in codes:
        t = trees[code]
        if t.nodes:
            interleaved.append(t.nodes[0])          # the root
            rests[code] = t.nodes[1:]
    idx = {code: 0 for code in rests}
    remaining = sum(len(v) for v in rests.values())
    while remaining:
        for code in codes:
            lst = rests.get(code)
            if lst is None or idx[code] >= len(lst):
                continue
            interleaved.append(lst[idx[code]])
            idx[code] += 1
            remaining -= 1

    return ParallelExpansion(trees=trees, interleaved=interleaved)