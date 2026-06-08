from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.generate import GenerateRequest, GeneratedNameResponse
from app.services.generated_names import search_generated_names


router = APIRouter(tags=["generate"])


@router.post("/generate", response_model=list[GeneratedNameResponse])
def generate_names(
    request: GenerateRequest,
    db: Session = Depends(get_db),
) -> list[GeneratedNameResponse]:
    return search_generated_names(db, request)