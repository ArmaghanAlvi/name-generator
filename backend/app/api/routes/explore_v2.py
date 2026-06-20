from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.explore_v2 import (
    ExpandedSenseResponse,
    ExploreV2Request,
    ExploreV2Response,
    ExploreV2Result,
)
from app.services.sense_selection import record_sense_selection
from app.services.vector_sense_search import expand_from_selected_senses


router = APIRouter(prefix="/explore-v2", tags=["explore-v2"])


@router.post("", response_model=ExploreV2Response)
def explore_v2(
    request: ExploreV2Request,
    db: Session = Depends(get_db),
) -> ExploreV2Response:
    for sense_id in request.selectedSenseIds:
        record_sense_selection(
            db,
            sense_id=sense_id,
            query_text=request.queryText,
        )

    hits = expand_from_selected_senses(
        db,
        selected_sense_ids=request.selectedSenseIds,
        expansion_count=request.expansionCount,
        target_language=request.language,
    )

    results: list[ExploreV2Result] = []
    expanded: list[ExpandedSenseResponse] = []

    for hit in hits:
        sense = hit.sense
        lexeme = sense.lexeme
        language = lexeme.language

        if not (
            request.minLength
            <= len(lexeme.lemma)
            <= request.maxLength
        ):
            continue

        if hit.match_type == "expanded":
            expanded.append(
                ExpandedSenseResponse(
                    senseId=sense.id,
                    word=lexeme.lemma,
                    language=language.name,
                    definition=sense.definition,
                    relationshipType=hit.reason,
                    weight=hit.score,
                )
            )

        results.append(
            ExploreV2Result(
                id=f"sense-{sense.id}",
                name=lexeme.lemma,
                category=(
                    "translation"
                    if hit.match_type == "expanded"
                    else "related"
                ),
                meaning=sense.definition,
                language=language.name,
                explanation=(
                    f"{lexeme.lemma} matched by {hit.reason} "
                    f"with score {hit.score:.3f}."
                ),
                matchType=(
                    "exact"
                    if hit.match_type == "selected"
                    else "expanded"
                ),
                matchedSenseId=sense.id,
                relationshipType=hit.reason,
                relationshipWeight=hit.score,
                partOfSpeech=lexeme.part_of_speech,
            )
        )

    db.commit()

    return ExploreV2Response(
        selectedSenseIds=request.selectedSenseIds,
        expandedSenses=expanded,
        results=results,
    )