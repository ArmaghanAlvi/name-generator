"""
Tiered candidate generator.

expand() is the entry point the API calls. It surfaces candidates in tiers:
  1. selected senses themselves (the 0th result)
  2. Kaikki synonym edges       (curated, highest precision)
  3. OEWN synonym edges         (orphan rescue breadth)
  4. OEWN near_synonym edges    (looser)
  5. vector fallback            (expand_from_selected_senses)

Edge tiers run BEFORE vector search so curated distinct synonyms (radiance,
glow, shine) are surfaced directly, rather than competing in vector ranking
where morphological families (illumin-/lumin-) crowd them out.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.semantic import Lexeme, Sense, SenseEmbedding, SenseRelation
from app.models.generated_name import Language
from app.utils.text import normalize_text
from app.services.morphology import same_family
from app.services.vector_sense_search import (
    SenseSearchHit,
    get_selected_senses,
    collect_antonym_lemmas,
    is_morphological_variant_of_query,
    word_length_allowed,
    display_word_key_for_sense,
    expand_from_selected_senses,
    _morph_stem,
)


# Edge tiers in priority order: (provenance, relation_type, reason-label)
_EDGE_TIERS = (
    ("kaikki", "synonym", "kaikki_synonym"),
    ("oewn", "synonym", "oewn_synonym"),
    ("oewn", "near_synonym", "oewn_near_synonym"),
)


def _resolve_lemma_to_display_sense(
    db: Session,
    normalized_lemma: str,
    target_language: str | None,
) -> Sense | None:
    """
    Pick the sense to DISPLAY for a synonym target lemma.

    Prefers an embedded, visible sense (consistent with what the vector path
    can show), lowest sense_index first (primary sense). Returns None if the
    lemma has no embedded visible sense — we don't surface unembedded junk.
    """
    stmt = (
        select(Sense)
        .options(selectinload(Sense.lexeme).selectinload(Lexeme.language))
        .join(Lexeme, Lexeme.id == Sense.lexeme_id)
        .join(Language, Language.id == Lexeme.language_id)
        .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)  # embedded only
        .where(
            Lexeme.normalized_lemma == normalized_lemma,
            Sense.visibility_status == "visible",
        )
        .order_by(Sense.sense_index)
        .limit(1)
    )
    if target_language is not None:
        stmt = stmt.where(Language.name == target_language)
    return db.scalars(stmt).first()


def _longest_common_substring_len(a: str, b: str) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _same_family(a: str, b: str) -> bool:
    """
    True if two lemmas are the same morphological family. Proportional to the
    shorter lemma's length so it works for both long words (illumination/
    luminance share 6) and short ones (joy/joyful share 3). Validated against
    lumin- and happy- families: groups true families, keeps distinct words
    (radiance vs luminance, joyful vs cheerful) separate.
    """
    shorter = min(len(a), len(b))
    if shorter == 0:
        return False
    threshold = max(3, -(-shorter * 6 // 10))  # ceil(0.6 * shorter), floor 3
    return _longest_common_substring_len(a, b) >= threshold


_FAMILY_PENALTY_STEP = 0.03


def _apply_family_diversity_penalty(
    hits: list[SenseSearchHit],
) -> list[SenseSearchHit]:
    """
    Soft-throttle morphological families so one root can't monopolize result
    slots. Keeps the strongest member penalty-free; penalizes each successive
    same-family member, then re-sorts. Never demotes the selected hit.
    """
    selected = [h for h in hits if h.match_type == "selected"]
    expanded = [h for h in hits if h.match_type != "selected"]
    expanded.sort(key=lambda h: h.score, reverse=True)

    kept_lemmas: list[str] = []
    rescored: list[SenseSearchHit] = []
    for h in expanded:
        lemma = normalize_text(h.sense.lexeme.lemma)
        family_count = sum(1 for k in kept_lemmas if same_family(lemma, k))
        penalty = _FAMILY_PENALTY_STEP * family_count
        rescored.append(SenseSearchHit(
            sense=h.sense,
            match_type=h.match_type,
            score=max(0.0, h.score - penalty),
            reason=(h.reason + f" | family-penalty -{penalty:.2f}") if penalty else h.reason,
        ))
        kept_lemmas.append(lemma)

    rescored.sort(key=lambda h: h.score, reverse=True)
    return selected + rescored


def expand(
    db: Session,
    *,
    selected_sense_ids: list[int],
    expansion_count: int,
    target_language: str | None = None,
    min_length: int = 0,
    max_length: int = 30,
    restrict_edges_to_selected: bool = False,
) -> list[SenseSearchHit]:
    selected_senses = get_selected_senses(db, sense_ids=selected_sense_ids)
    if not selected_senses:
        return []

    selected_lemmas = {normalize_text(s.lexeme.lemma) for s in selected_senses}
    selected_stems = {_morph_stem(s.lexeme.lemma) for s in selected_senses}
    antonym_lemmas = collect_antonym_lemmas(selected_senses)

    # Over-collect so the family penalty has alternatives to promote.
    collect_target = max(expansion_count * 3, expansion_count + 5)

    hits: list[SenseSearchHit] = []
    displayed: set[str] = set()

    # --- Tier 0: the selected senses themselves ---
    for sense in selected_senses:
        if not word_length_allowed(sense, min_length=min_length, max_length=max_length):
            continue
        key = display_word_key_for_sense(sense)
        if key in displayed:
            continue
        displayed.add(key)
        hits.append(SenseSearchHit(
            sense=sense, match_type="selected", score=1.0,
            reason="user_selected_meaning",
        ))

    def expanded_count() -> int:
        return len([h for h in hits if h.match_type == "expanded"])

    # --- Tiers 1-3: collect synonym-edge candidates ---
    if restrict_edges_to_selected:
        # Hop mode: ONLY the passed sense's own edges. Stops a non-primary
        # sense (foul=weather) from inheriting another sense's edges
        # (foul=dirty -> funky/unclean) via whole-lexeme collection.
        edge_source_sense_ids = [s.id for s in selected_senses]
    else:
        # Root mode: all senses of the lexeme. Edges concentrate on the
        # primary sense (Stage 3), so a user picking a non-primary sense
        # still reaches the lexeme's parked synonym edges.
        selected_lexeme_ids = {s.lexeme_id for s in selected_senses}
        edge_source_sense_ids = [
            sid for (sid,) in db.execute(
                select(Sense.id).where(Sense.lexeme_id.in_(selected_lexeme_ids))
            ).all()
        ]

    edge_candidates: list[tuple[Sense, str]] = []
    seen_targets: set[str] = set()
    for provenance, rel_type, reason in _EDGE_TIERS:
        edges = db.execute(
            select(SenseRelation.target_normalized).where(
                SenseRelation.from_sense_id.in_(edge_source_sense_ids),
                SenseRelation.relation_type == rel_type,
                SenseRelation.provenance == provenance,
            )
        ).all()
        for (norm,) in edges:
            if not norm or norm in seen_targets:
                continue
            seen_targets.add(norm)
            if norm in selected_lemmas or norm in antonym_lemmas:
                continue
            cand = _resolve_lemma_to_display_sense(db, norm, target_language)
            if cand is None:
                continue
            if is_morphological_variant_of_query(
                cand.lexeme.lemma, selected_lemmas, selected_stems,
            ):
                continue
            if not word_length_allowed(cand, min_length=min_length, max_length=max_length):
                continue
            key = display_word_key_for_sense(cand)
            if key in displayed:
                continue
            displayed.add(key)
            edge_candidates.append((cand, reason))

    # --- Score edge candidates by cosine similarity to the query ---
    if edge_candidates:
        from app.services.embedding_provider import embed_query
        from app.services.vector_sense_search import build_query_text_from_selected_senses

        query_vector = embed_query(
            build_query_text_from_selected_senses(selected_senses)
        )
        cand_ids = [c.id for c, _ in edge_candidates]
        dist_rows = db.execute(
            select(
                SenseEmbedding.sense_id,
                SenseEmbedding.embedding.cosine_distance(query_vector).label("d"),
            ).where(SenseEmbedding.sense_id.in_(cand_ids))
        ).all()
        dist_by_id = {sid: float(d) for sid, d in dist_rows}

        scored = sorted(
            (
                (max(0.0, 1.0 - dist_by_id.get(cand.id, 1.0)), cand, reason)
                for cand, reason in edge_candidates
            ),
            key=lambda x: x[0],
            reverse=True,
        )
        for score, cand, reason in scored:
            hits.append(SenseSearchHit(
                sense=cand, match_type="expanded", score=score, reason=reason,
            ))
            if expanded_count() >= collect_target:
                break

    # --- Tier 4: vector fallback for remaining slots ---
    if expanded_count() < collect_target:
        vector_hits = expand_from_selected_senses(
            db,
            selected_sense_ids=selected_sense_ids,
            expansion_count=collect_target - expanded_count() + len(displayed),
            target_language=target_language,
            min_length=min_length,
            max_length=max_length,
        )
        for vh in vector_hits:
            if vh.match_type == "selected":
                continue
            key = display_word_key_for_sense(vh.sense)
            if key in displayed:
                continue
            displayed.add(key)
            hits.append(vh)
            if expanded_count() >= collect_target:
                break

    # --- Family diversity throttle, then truncate to requested count ---
    hits = _apply_family_diversity_penalty(hits)
    selected_hits = [h for h in hits if h.match_type == "selected"]
    expanded_hits = [h for h in hits if h.match_type != "selected"][:expansion_count]
    return selected_hits + expanded_hits