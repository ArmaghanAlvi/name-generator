from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.explore_v2 import (
    ExpandedSenseResponse,
    ExploreV2Request,
    ExploreV2Response,
    ExploreV2Result,
    HopPathStep,
)
from app.services.sense_selection import record_sense_selection
from app.services.expansion import expand
from app.services.multi_hop_expansion import multi_hop_expand, HopNode

router = APIRouter(prefix="/explore-v2", tags=["explore-v2"])


def _hopnode_to_result(node: HopNode) -> ExploreV2Result:
    sense = node.sense
    lexeme = sense.lexeme
    language = lexeme.language
    is_selected = node.depth == 0
    path = [
        HopPathStep(word=w, senseId=sid, depth=i)
        for i, (w, sid) in enumerate(zip(node.path, node.path_sense_ids))
    ]
    return ExploreV2Result(
        id=f"sense-{sense.id}",
        name=lexeme.lemma,
        category="translation",
        meaning=sense.definition,
        language=language.name,
        explanation=(
            f"{lexeme.lemma} reached via {'>'.join(node.path)} "
            f"(hop {node.depth}, {node.provenance}, score {node.anchored_score:.3f})."
        ),
        matchType="exact" if is_selected else "expanded",
        matchedSenseId=sense.id,
        relationshipType=node.provenance,
        relationshipWeight=node.anchored_score,
        partOfSpeech=lexeme.part_of_speech,
        depth=node.depth,
        parentSenseId=node.parent_sense_id,
        provenance=node.provenance,
        path=path,
    )


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

    results: list[ExploreV2Result] = []
    expanded: list[ExpandedSenseResponse] = []

    if request.depth > 1:
        # --- Multi-hop path ---
        width = request.width if request.width is not None else request.expansionCount
        nodes = multi_hop_expand(
            db,
            root_sense_id=request.selectedSenseIds[0],
            width=width,
            depth=request.depth,
            target_language=request.language,
            min_length=request.minLength,
            max_length=request.maxLength,
        )
        for node in nodes:
            if node.depth > 0:  # expanded subset -> expandedSenses (lean shape)
                expanded.append(
                    ExpandedSenseResponse(
                        senseId=node.sense.id,
                        word=node.sense.lexeme.lemma,
                        language=node.sense.lexeme.language.name,
                        definition=node.sense.definition,
                        relationshipType=node.provenance,
                        weight=node.anchored_score,
                    )
                )
            results.append(_hopnode_to_result(node))
    else:
        # --- Single-hop path (unchanged behavior) ---
        hits = expand(
            db,
            selected_sense_ids=request.selectedSenseIds,
            expansion_count=request.expansionCount,
            target_language=request.language,
            min_length=request.minLength,
            max_length=request.maxLength,
        )
        for hit in hits:
            sense = hit.sense
            lexeme = sense.lexeme
            language = lexeme.language
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
                    category="translation",
                    meaning=sense.definition,
                    language=language.name,
                    explanation=(
                        f"{lexeme.lemma} matched by {hit.reason} "
                        f"with score {hit.score:.3f}."
                    ),
                    matchType=(
                        "exact" if hit.match_type == "selected" else "expanded"
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