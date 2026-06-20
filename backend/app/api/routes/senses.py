from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.senses import SenseLookupResponse
from app.services.sense_lookup import lookup_sense_options


router = APIRouter(prefix="/senses", tags=["senses"])


@router.get("/lookup", response_model=SenseLookupResponse)
def lookup_senses(
    query: str = Query(min_length=1),
    languageCode: str | None = None,
    includeHidden: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> SenseLookupResponse:
    options = lookup_sense_options(
        db,
        query=query,
        language_code=languageCode,
        include_hidden=includeHidden,
        limit=limit,
    )

    return SenseLookupResponse(
        query=query,
        options=options,
    )