from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.explore import ExploreRequest, ExploreResponse
from app.services.semantic_search import explore_meanings


router = APIRouter(tags=["explore"])


@router.post("/explore", response_model=ExploreResponse)
def explore(
    request: ExploreRequest,
    db: Session = Depends(get_db),
) -> ExploreResponse:
    return explore_meanings(db, request)