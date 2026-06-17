from dataclasses import dataclass
from typing import Literal

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.generated_name import GeneratedName, Language
from app.models.semantic import (
    Concept,
    ConceptAlias,
    ConceptMapping,
    ConceptRelationship,
    EstablishedName,
    NameMeaning,
    Root,
    RootMeaning,
    Source,
    Word,
    WordSense,
)
from app.schemas.explore import (
    ExpandedConceptResponse,
    ExploreRequest,
    ExploreResponse,
    ResultResponse,
)

from app.utils.text import normalize_text

MatchType = Literal["exact", "expanded"]

EQUIVALENCE_PRIORITY = {
    "canonical": 0,
    "direct_equivalent": 1,
    "near_equivalent": 2,
    "related": 3,
    "symbolic": 4,
    "poetic": 5,
    "archaic": 6,
    "technical": 7,
}

CONFIDENCE_PRIORITY = {
    "high": 0,
    "medium": 1,
    "low": 2,
}


@dataclass(frozen=True)
class SelectedConcept:
    """
    Internal representation of a concept selected for a search.

    Exact concepts come directly from the user's input.
    Expanded concepts come from ConceptRelationship rows.
    """

    concept: Concept
    match_type: MatchType
    relationship_type: str | None = None
    weight: float | None = None


def format_with_transliteration(
    text: str,
    transliteration: str | None,
) -> str:
    """
    Display native-script text alongside a romanized form
    when a transliteration exists.

    Examples:
        نور (nūr)
        光 (hikari)
        lux
    """

    if transliteration is None:
        return text

    return f"{text} ({transliteration})"


def resolve_exact_concepts(
    db: Session,
    meanings: list[str],
) -> list[SelectedConcept]:
    """
    Convert typed meanings into canonical concepts.

    Example:
        "light" -> Concept(slug="illumination")

    The lookup primarily uses ConceptAlias. A direct Concept.slug
    lookup is included as a fallback so that canonical slugs also work.
    """

    normalized_meanings = [
        normalize_text(meaning)
        for meaning in meanings
        if normalize_text(meaning)
    ]

    if not normalized_meanings:
        return []

    alias_statement = (
        select(ConceptAlias)
        .options(
            selectinload(ConceptAlias.concept),
        )
        .where(
            ConceptAlias.normalized_text.in_(normalized_meanings),
        )
    )

    aliases = list(
        db.scalars(alias_statement).all()
    )

    aliases_by_text: dict[str, list[Concept]] = {}

    for alias in aliases:
        aliases_by_text.setdefault(
            alias.normalized_text,
            [],
        ).append(alias.concept)

    slug_statement = (
        select(Concept)
        .where(
            Concept.slug.in_(normalized_meanings),
        )
    )

    concepts_by_slug = {
        concept.slug: concept
        for concept in db.scalars(slug_statement).all()
    }

    selected: list[SelectedConcept] = []
    seen_concept_ids: set[int] = set()

    for meaning in normalized_meanings:
        matching_concepts = aliases_by_text.get(
            meaning,
            [],
        )

        if not matching_concepts:
            matching_slug = concepts_by_slug.get(meaning)

            if matching_slug is not None:
                matching_concepts = [matching_slug]

        for concept in matching_concepts:
            if concept.id in seen_concept_ids:
                continue

            if concept.status != "active":
                continue

            if not concept.is_public:
                continue

            seen_concept_ids.add(concept.id)

            selected.append(
                SelectedConcept(
                    concept=concept,
                    match_type="exact",
                )
            )

    return selected


def expand_concepts(
    db: Session,
    exact_concepts: list[SelectedConcept],
    expansion_count: int,
) -> list[SelectedConcept]:
    """
    Add the strongest related concepts.

    The expansion count is global rather than per meaning.

    Example:
        light + 0 expansions
            -> illumination

        light + 2 expansions
            -> illumination, radiance, clarity

        light + 3 expansions
            -> illumination, radiance, clarity, dawn
    """

    if expansion_count <= 0:
        return []

    if not exact_concepts:
        return []

    exact_concept_ids = {
        selected.concept.id
        for selected in exact_concepts
    }

    relationship_statement = (
        select(ConceptRelationship)
        .options(
            selectinload(
                ConceptRelationship.target_concept
            ),
        )
        .where(
            ConceptRelationship.source_concept_id.in_(
                exact_concept_ids
            ),
            ConceptRelationship.review_status == "reviewed",
            ConceptRelationship.confidence.in_(["high", "medium"]),
        )
        .order_by(
            desc(ConceptRelationship.weight),
            ConceptRelationship.id,
        )
    )

    relationships = list(
        db.scalars(relationship_statement).all()
    )

    expanded: list[SelectedConcept] = []
    seen_concept_ids = set(exact_concept_ids)

    for relationship in relationships:
        target = relationship.target_concept

        if target.id in seen_concept_ids:
            continue

        if target.status != "active":
            continue

        if not target.is_public:
            continue

        seen_concept_ids.add(target.id)

        expanded.append(
            SelectedConcept(
                concept=target,
                match_type="expanded",
                relationship_type=(
                    relationship.relationship_type
                ),
                weight=relationship.weight,
            )
        )

        if len(expanded) >= expansion_count:
            break

    return expanded


def index_selected_concepts(
    concepts: list[SelectedConcept],
) -> dict[int, SelectedConcept]:
    """
    Create a lookup table keyed by concept ID.

    This allows result-building functions to quickly determine
    whether a matching row is exact or expanded.
    """

    return {
        selected.concept.id: selected
        for selected in concepts
    }


def choose_best_selected_concept(
    candidate_concepts: list[Concept],
    selected_by_id: dict[int, SelectedConcept],
) -> SelectedConcept | None:
    """
    Choose the best selected concept for a generated name.

    A generated name may be connected to multiple concepts.
    Exact matches take priority over expanded matches.
    Higher-weight expanded concepts take priority over weaker ones.
    """

    matches = [
        selected_by_id[concept.id]
        for concept in candidate_concepts
        if concept.id in selected_by_id
    ]

    if not matches:
        return None

    def priority(
        selected: SelectedConcept,
    ) -> tuple[int, float]:
        if selected.match_type == "exact":
            return (0, 0.0)

        return (
            1,
            -(selected.weight or 0.0),
        )

    return min(matches, key=priority)


def build_sense_concept_selection_map(
    db: Session,
    selected_by_id: dict[int, SelectedConcept],
) -> dict[int, SelectedConcept]:
    """
    Return a lookup from concept_id to the SelectedConcept that
    should explain the result.

    This includes:
    - directly selected public concepts
    - external synset concepts mapped to selected public concepts
    """

    if not selected_by_id:
        return {}

    sense_concept_to_selected: dict[int, SelectedConcept] = dict(
        selected_by_id
    )

    mapping_statement = (
        select(ConceptMapping)
        .options(
            selectinload(ConceptMapping.source_concept),
            selectinload(ConceptMapping.target_concept),
        )
        .where(
            ConceptMapping.target_concept_id.in_(
                list(selected_by_id)
            ),
            ConceptMapping.review_status == "reviewed",
        )
    )

    mappings = list(
        db.scalars(mapping_statement).all()
    )

    for mapping in mappings:
        selected = selected_by_id.get(
            mapping.target_concept_id
        )

        if selected is None:
            continue

        sense_concept_to_selected[
            mapping.source_concept_id
        ] = selected

    return sense_concept_to_selected


def build_word_results(
    db: Session,
    *,
    selected_by_id: dict[int, SelectedConcept],
    request: ExploreRequest,
) -> list[ResultResponse]:
    query_terms = {
        normalize_text(meaning)
        for meaning in request.meanings
    }

    concept_ids = list(selected_by_id)

    if not concept_ids:
        return []

    statement = (
        select(WordSense)
        .join(WordSense.word)
        .options(
            selectinload(WordSense.word).selectinload(
                Word.language
            ),
            selectinload(WordSense.source),
            selectinload(WordSense.concept),
        )
        .where(
            WordSense.concept_id.in_(concept_ids),
            WordSense.review_status == "reviewed",
            WordSense.confidence.in_(["high", "medium"]),
            func.char_length(Word.text).between(
                request.minLength,
                request.maxLength,
            ),
        )
    )

    if request.language is not None:
        statement = statement.where(
            Word.language.has(
                Language.name == request.language
            )
        )

    senses = list(db.scalars(statement).all())

    best_by_concept_language: dict[tuple[int, int], WordSense] = {}

    for sense in senses:
        selected = selected_by_id[sense.concept_id]

        key = (
            sense.concept_id,
            sense.word.language_id,
        )

        existing = best_by_concept_language.get(key)

        candidate_priority = word_sense_priority(
            sense,
            query_terms,
            is_exact_concept=selected.match_type == "exact",
        )

        if existing is None:
            best_by_concept_language[key] = sense
            continue

        existing_priority = word_sense_priority(
            existing,
            query_terms,
            is_exact_concept=selected.match_type == "exact",
        )

        if candidate_priority < existing_priority:
            best_by_concept_language[key] = sense

    selected_senses = sorted(
        best_by_concept_language.values(),
        key=lambda sense: (
            0
            if selected_by_id[sense.concept_id].match_type == "exact"
            else 1,
            -(
                selected_by_id[sense.concept_id].weight
                or 1.0
            ),
            sense.word.language.name,
            word_sense_priority(
                sense,
                query_terms,
                is_exact_concept=(
                    selected_by_id[sense.concept_id].match_type
                    == "exact"
                ),
            ),
        ),
    )

    results: list[ResultResponse] = []

    for sense in selected_senses:
        word = sense.word
        selected = selected_by_id[sense.concept_id]

        results.append(
            ResultResponse(
                id=f"word-sense-{sense.id}",
                name=format_with_transliteration(
                    word.text,
                    word.transliteration,
                ),
                category="translation",
                meaning=sense.gloss,
                language=word.language.name,
                explanation=(
                    word.notes
                    or f"{word.text} is associated with {sense.gloss}."
                ),
                matchType=selected.match_type,
                matchedConcept=selected.concept.slug,
                relationshipType=selected.relationship_type,
                relationshipWeight=selected.weight,
                equivalenceType=sense.equivalence_type,
                senseRank=sense.sense_rank,
                source=sense.source.name if sense.source else None,
                sourceLocator=sense.source_locator,
                confidence=sense.confidence,
            )
        )

    return results


def build_established_name_results(
    db: Session,
    *,
    selected_by_id: dict[int, SelectedConcept],
    request: ExploreRequest,
) -> list[ResultResponse]:
    """
    Build green-card established-name results.

    Expanded matches use the 'related' category so the frontend
    can visually distinguish them from direct matches.
    """

    concept_ids = list(selected_by_id)

    if not concept_ids:
        return []

    statement = (
        select(NameMeaning)
        .join(NameMeaning.established_name)
        .options(
            selectinload(
                NameMeaning.established_name
            ).selectinload(
                EstablishedName.language
            ),
        )
        .where(
            NameMeaning.concept_id.in_(concept_ids),
            func.char_length(
                EstablishedName.name
            ).between(
                request.minLength,
                request.maxLength,
            ),
        )
    )

    if request.language is not None:
        statement = statement.where(
            EstablishedName.language.has(
                Language.name == request.language
            )
        )

    meanings = list(
        db.scalars(statement).all()
    )

    results: list[ResultResponse] = []

    for meaning in meanings:
        established_name = meaning.established_name
        selected = selected_by_id[meaning.concept_id]

        category: Literal["established", "related"]

        if selected.match_type == "exact":
            category = "established"
        else:
            category = "related"

        results.append(
            ResultResponse(
                id=(
                    f"established-name-"
                    f"{established_name.id}-"
                    f"{meaning.concept_id}"
                ),
                name=established_name.name,
                category=category,
                meaning=selected.concept.label,
                language=established_name.language.name,
                explanation=meaning.explanation,
                matchType=selected.match_type,
                matchedConcept=selected.concept.slug,
            )
        )

    return results


def build_root_results(
    db: Session,
    *,
    selected_by_id: dict[int, SelectedConcept],
    request: ExploreRequest,
) -> list[ResultResponse]:
    """
    Build pink-card root results.
    """

    concept_ids = list(selected_by_id)

    if not concept_ids:
        return []

    statement = (
        select(RootMeaning)
        .join(RootMeaning.root)
        .options(
            selectinload(RootMeaning.root).selectinload(
                Root.language
            ),
        )
        .where(
            RootMeaning.concept_id.in_(concept_ids),
            func.char_length(Root.text).between(
                request.minLength,
                request.maxLength,
            ),
        )
    )

    if request.language is not None:
        statement = statement.where(
            Root.language.has(
                Language.name == request.language
            )
        )

    meanings = list(
        db.scalars(statement).all()
    )

    results: list[ResultResponse] = []

    for meaning in meanings:
        root = meaning.root
        selected = selected_by_id[meaning.concept_id]

        explanation_parts = [
            f"Root type: {root.root_type}.",
            f"Meaning: {meaning.gloss}.",
        ]

        if root.notes:
            explanation_parts.append(root.notes)

        results.append(
            ResultResponse(
                id=f"root-{root.id}-{meaning.concept_id}",
                name=format_with_transliteration(
                    root.text,
                    root.transliteration,
                ),
                category="root",
                meaning=meaning.gloss,
                language=root.language.name,
                explanation=" ".join(explanation_parts),
                matchType=selected.match_type,
                matchedConcept=selected.concept.slug,
            )
        )

    return results


def build_generated_name_results(
    db: Session,
    *,
    selected_by_id: dict[int, SelectedConcept],
    request: ExploreRequest,
) -> list[ResultResponse]:
    """
    Build blue-card generated-name results.

    Generated names may match more than one selected concept.
    The strongest matching concept is chosen for the card badge.
    """

    concept_ids = list(selected_by_id)

    if not concept_ids:
        return []

    statement = (
        select(GeneratedName)
        .join(GeneratedName.concepts)
        .options(
            selectinload(GeneratedName.source_languages),
            selectinload(GeneratedName.flavors),
            selectinload(GeneratedName.parts),
            selectinload(GeneratedName.concepts),
        )
        .where(
            Concept.id.in_(concept_ids),
            func.char_length(GeneratedName.name).between(
                request.minLength,
                request.maxLength,
            ),
        )
        .distinct()
    )

    if request.language is not None:
        statement = statement.where(
            GeneratedName.source_languages.any(
                Language.name == request.language
            )
        )

    generated_names = list(
        db.scalars(statement).all()
    )

    results: list[ResultResponse] = []

    for generated_name in generated_names:
        selected = choose_best_selected_concept(
            generated_name.concepts,
            selected_by_id,
        )

        if selected is None:
            continue

        source_languages = [
            language.name
            for language in generated_name.source_languages
        ]

        language_label = (
            ", ".join(source_languages)
            if source_languages
            else "Crafted"
        )

        results.append(
            ResultResponse(
                id=f"generated-name-{generated_name.id}",
                name=generated_name.name,
                category="generated",
                meaning=generated_name.meaning,
                language=language_label,
                explanation=generated_name.explanation,
                matchType=selected.match_type,
                matchedConcept=selected.concept.slug,
                sourceLanguages=source_languages,
                flavors=[
                    flavor.name
                    for flavor in generated_name.flavors
                ],
                parts=[
                    {
                        "text": part.text,
                        "meaning": part.meaning,
                        "language": part.language,
                        "kind": part.kind,
                        "note": part.note,
                    }
                    for part in generated_name.parts
                ],
            )
        )

    return results


def explore_meanings(
    db: Session,
    request: ExploreRequest,
) -> ExploreResponse:
    """
    Main semantic-search entry point.

    This is the function your /explore route will call.
    """

    exact_concepts = resolve_exact_concepts(
        db,
        request.meanings,
    )

    expanded_concepts = expand_concepts(
        db,
        exact_concepts,
        request.expansionCount,
    )

    selected_concepts = [
        *exact_concepts,
        *expanded_concepts,
    ]

    selected_by_id = index_selected_concepts(
        selected_concepts
    )

    results = [
        *build_word_results(
            db,
            selected_by_id=selected_by_id,
            request=request,
        ),
        *build_established_name_results(
            db,
            selected_by_id=selected_by_id,
            request=request,
        ),
        *build_root_results(
            db,
            selected_by_id=selected_by_id,
            request=request,
        ),
        *build_generated_name_results(
            db,
            selected_by_id=selected_by_id,
            request=request,
        ),
    ]

    return ExploreResponse(
        matchedConcepts=[
            selected.concept.slug
            for selected in exact_concepts
        ],
        expandedConcepts=[
            ExpandedConceptResponse(
                slug=selected.concept.slug,
                label=selected.concept.label,
                relationshipType=(
                    selected.relationship_type
                    or "related"
                ),
                weight=selected.weight or 0.0,
            )
            for selected in expanded_concepts
        ],
        results=results,
    )


def word_sense_priority(
    sense: WordSense,
    query_terms: set[str],
    *,
    is_exact_concept: bool,
) -> tuple[int, int, int, int, str]:
    query_match_bonus = (
        0
        if is_exact_concept
        and sense.word.normalized_text in query_terms
        else 1
    )

    return (
        query_match_bonus,
        EQUIVALENCE_PRIORITY.get(
            sense.equivalence_type,
            99,
        ),
        sense.sense_rank,
        CONFIDENCE_PRIORITY.get(
            sense.confidence,
            99,
        ),
        sense.word.text,
    )