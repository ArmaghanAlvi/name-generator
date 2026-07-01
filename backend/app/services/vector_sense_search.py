from __future__ import annotations

import logging

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.generated_name import Language
from app.models.semantic import Lexeme, Sense, SenseEmbedding
from app.services.embedding_provider import DEFAULT_EMBEDDING_MODEL, embed_query
from app.utils.text import normalize_text
from app.services.sense_selection import get_sense_selection_counts_for_senses
from app.services.sense_reranker import (
    RerankCandidate,
    rerank_candidates,
)

logger = logging.getLogger(__name__)

# Cosine-similarity floor for vector expansions. Candidates whose FINAL
# reranked score falls below this are treated as "not a real synonym" and
# dropped, even if it means returning fewer than expansion_count results.
# 0.0 distance = identical; we keep ~0.70+ similarity. Tune in Stage 6.
MIN_EXPANSION_SCORE = 0.78

MatchType = Literal["selected", "expanded"]


@dataclass(frozen=True)
class SenseSearchHit:
    sense: Sense
    match_type: MatchType
    score: float
    reason: str


# Common inflectional/derivational endings we strip to detect that a
# candidate is "the same word" as the query (light/lighted/lighting/lights).
_MORPH_SUFFIXES = (
    "ing", "edly", "ed", "es", "s",
    "er", "est", "ly", "ness", "ment", "tion", "ion",
)


def _morph_stem(text: str) -> str:
    """
    Crude, dependency-free stem: lowercase, then strip one common suffix.
    Good enough to catch light/lighted/lighting/lights as one family.
    Not linguistically perfect, and that's fine — we only use it to reject
    same-word candidates, never to merge distinct words.
    """
    base = normalize_text(text)

    for suffix in _MORPH_SUFFIXES:
        if len(base) > len(suffix) + 2 and base.endswith(suffix):
            return base[: -len(suffix)]

    return base


def is_morphological_variant_of_query(
    candidate_lemma: str,
    selected_lemmas: set[str],
    selected_stems: set[str],
) -> bool:
    """
    True if the candidate is essentially the same word as a selected lemma:
    an exact match, a shared stem, or a long shared prefix. Used to drop
    'lighted'/'lighting' when the query is 'light'.
    """
    normalized = normalize_text(candidate_lemma)

    if normalized in selected_lemmas:
        return True

    candidate_stem = _morph_stem(normalized)

    if candidate_stem in selected_stems:
        return True

    # Long shared prefix catches cases the suffix list misses
    # (e.g. 'luminous' vs 'luminosity' share 'lumin').
    for stem in selected_stems:
        shared = _shared_prefix_length(candidate_stem, stem)

        if shared >= 5 and shared >= min(len(candidate_stem), len(stem)) - 1:
            return True

    return False


def _shared_prefix_length(a: str, b: str) -> int:
    count = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        count += 1
    return count


def display_word_key_for_sense(sense: Sense) -> str:
    """
    Determines whether two sense results count as the same displayed word.

    For now, this dedupes globally by displayed lemma:
        light/noun and light/adjective collapse to "light"

    Later, if you want to allow same spelling across different languages,
    change this to include language code.
    """
    return normalize_text(sense.lexeme.lemma)


def word_length_allowed(
    sense: Sense,
    *,
    min_length: int,
    max_length: int,
) -> bool:
    length = len(sense.lexeme.lemma)

    return min_length <= length <= max_length


def build_query_text_from_selected_senses(
    senses: list[Sense],
) -> str:
    """
    Build a lean query string for E5.

    E5 embeds text literally; it does not follow instructions. So we
    include ONLY meaning-bearing content (lemma + definition + a couple
    of glosses), not prose describing what we want. A tight query of the
    form "lemma: <definition>" matches near-synonyms far better than an
    instruction paragraph, which drags the vector toward meta-vocabulary
    like "poetic" and "equivalent".
    """
    parts: list[str] = []

    from app.services.sense_embeddings import collect_synonyms_for_embedding
    for sense in senses:
        lexeme = sense.lexeme
        extra_glosses = "; ".join(sense.raw_glosses[1:3])
        fragment = f"{lexeme.lemma}: {sense.definition}"
        if extra_glosses:
            fragment = f"{fragment}; {extra_glosses}"
        synonyms = collect_synonyms_for_embedding(sense)
        if synonyms:
            fragment = f"{fragment}; synonyms: {', '.join(synonyms)}"
        parts.append(fragment)

    return " ".join(parts)


def get_selected_senses(
    db: Session,
    *,
    sense_ids: list[int],
) -> list[Sense]:
    if not sense_ids:
        return []

    return list(
        db.scalars(
            select(Sense)
            .options(
                selectinload(Sense.lexeme).selectinload(Lexeme.language),
                selectinload(Sense.relations),
            )
            .where(
                Sense.id.in_(sense_ids),
                Sense.visibility_status == "visible",
            )
        ).all()
    )


def collect_antonym_lemmas(selected_senses: list[Sense]) -> set[str]:
    """
    Normalized lemmas that are antonyms of any selected sense. Used to drop
    candidates like 'dark'/'darkness' that cluster near 'light' in vector
    space precisely because antonyms share context. Requires sense.relations
    to be loaded.
    """
    out: set[str] = set()
    for sense in selected_senses:
        for rel in (getattr(sense, "relations", None) or []):
            if rel.relation_type == "antonym":
                out.add(normalize_text(rel.target_text))
    return out


def expand_from_selected_senses(
    db: Session,
    *,
    selected_sense_ids: list[int],
    expansion_count: int,
    target_language: str | None = None,
    min_length: int = 0,
    max_length: int = 30,
) -> list[SenseSearchHit]:
    selected_senses = get_selected_senses(
        db,
        sense_ids=selected_sense_ids,
    )
    selected_lemmas = {
        normalize_text(sense.lexeme.lemma)
        for sense in selected_senses
    }
    selected_stems = {
        _morph_stem(sense.lexeme.lemma)
        for sense in selected_senses
    }
    antonym_lemmas = collect_antonym_lemmas(selected_senses)

    hits: list[SenseSearchHit] = []
    displayed_word_keys: set[str] = set()

    # 0th expansion:
    # Show the exact selected meaning, but only once per displayed word.
    for sense in selected_senses:
        if not word_length_allowed(
            sense,
            min_length=min_length,
            max_length=max_length,
        ):
            continue

        word_key = display_word_key_for_sense(sense)

        if word_key in displayed_word_keys:
            continue

        displayed_word_keys.add(word_key)

        hits.append(
            SenseSearchHit(
                sense=sense,
                match_type="selected",
                score=1.0,
                reason="user_selected_meaning",
            )
        )

    if expansion_count <= 0 or not selected_senses:
        return hits

    query_text = build_query_text_from_selected_senses(selected_senses)
    query_vector = embed_query(query_text)

    selected_lexeme_ids = {sense.lexeme_id for sense in selected_senses}
    # Exclude EVERY sense of the queried lexeme(s), not just the selected
    # sense — otherwise light's ~70 other senses (near-identical embeddings)
    # flood the candidate pool and crowd out genuinely different words.
    selected_ids = set(
        db.scalars(
            select(Sense.id).where(Sense.lexeme_id.in_(selected_lexeme_ids))
        ).all()
    )

    distance = SenseEmbedding.embedding.cosine_distance(query_vector)

    # Important:
    # We fetch more than the requested expansion count because many nearby
    # vector hits may be duplicate senses of the same displayed word.
    candidate_fetch_limit = min(
        max(expansion_count * 50, 100),
        1000,
    )

    statement = (
        select(SenseEmbedding, distance.label("distance"))
        .join(Sense, Sense.id == SenseEmbedding.sense_id)
        .join(Lexeme, Lexeme.id == Sense.lexeme_id)
        .join(Language, Language.id == Lexeme.language_id)
        .options(
            selectinload(SenseEmbedding.sense)
            .selectinload(Sense.lexeme)
            .selectinload(Lexeme.language)
        )
        .where(
            SenseEmbedding.embedding_model == DEFAULT_EMBEDDING_MODEL,
            Sense.visibility_status == "visible",
            ~SenseEmbedding.sense_id.in_(selected_ids),
        )
    )

    if target_language is not None:
        statement = statement.where(Language.name == target_language)

    rows = db.execute(
        statement.order_by(distance).limit(candidate_fetch_limit)
    ).all()

    logger.debug("fetched %d candidate rows from pgvector", len(rows))

    candidate_groups: dict[str, list[RerankCandidate]] = {}

    for embedding, raw_distance in rows:
        sense = embedding.sense

        if not word_length_allowed(
            sense,
            min_length=min_length,
            max_length=max_length,
        ):
            continue

        word_key = display_word_key_for_sense(sense)

        # The exact selected word is already shown as the 0th result.
        if word_key in displayed_word_keys:
            continue

        # Drop morphological variants of the query (lighted/lighting/lights).
        if is_morphological_variant_of_query(
            sense.lexeme.lemma,
            selected_lemmas,
            selected_stems,
        ):
            continue
        
        # Drop antonyms (dark/darkness for light) — they cluster by shared
        # context but are the opposite meaning.
        if normalize_text(sense.lexeme.lemma) in antonym_lemmas:
            continue

        distance_value = float(raw_distance)
        vector_score = max(0.0, 1.0 - distance_value)

        candidate_groups.setdefault(word_key, []).append(
            RerankCandidate(
                sense=sense,
                vector_score=vector_score,
            )
        )

    duplicate_candidates = [
        candidate
        for group in candidate_groups.values()
        for candidate in group
    ]

    duplicate_candidate_senses = [
        candidate.sense
        for candidate in duplicate_candidates
    ]

    sense_selection_counts = get_sense_selection_counts_for_senses(
        db,
        senses=duplicate_candidate_senses,
    )

    def duplicate_candidate_sort_key(
        candidate: RerankCandidate,
    ) -> tuple[int, float]:
        # If multiple candidate senses have the same displayed word, choose the
        # exact meaning that has been selected/searched most often.
        # If selection counts tie, keep the strongest vector match.
        return (
            sense_selection_counts.get(candidate.sense.id, 0),
            candidate.vector_score,
        )

    rerank_candidates_input = [
        max(group, key=duplicate_candidate_sort_key)
        for group in candidate_groups.values()
    ]

    reranked = rerank_candidates(
        candidates=rerank_candidates_input,
        sense_selection_counts=sense_selection_counts,
    )

    expanded_added = 0

    logger.debug("%d reranked candidates", len(reranked))
    if logger.isEnabledFor(logging.DEBUG):
        for r in reranked[:15]:
            logger.debug("  %-20s score=%.3f", r.sense.lexeme.lemma, r.final_score)

    for result in reranked:
        if expanded_added >= expansion_count:
            break

        if result.final_score < MIN_EXPANSION_SCORE:
            # reranked is sorted desc, so everything after is weaker.
            break

        hits.append(
            SenseSearchHit(
                sense=result.sense,
                match_type="expanded",
                score=result.final_score,
                reason=(
                    "pgvector_similarity_auto_reranked: "
                    + " | ".join(result.explanation_parts)
                ),
            )
        )
        expanded_added += 1

    return hits