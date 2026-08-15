"""
GET /languages -- the imported-language directory (Breakdown 5).

DB-derived exactly like the interleave order (Breakdown 4, Step 1d): every
language with visible senses, ascending language id, English pinned first.
`rtl` is computed from the ISO 15924 script column so future RTL languages
(he, fa) are correct at import time with zero frontend changes.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.language_directory import visible_languages

router = APIRouter(prefix="/languages", tags=["languages"])

_RTL_SCRIPTS = {"Arab", "Hebr"}


class LanguageInfo(BaseModel):
    code: str
    name: str
    nativeName: str | None
    script: str | None
    rtl: bool


@router.get("", response_model=list[LanguageInfo])
def list_languages(db: Session = Depends(get_db)) -> list[LanguageInfo]:
    # Query shape and cache live in services/language_directory (roadmap C1).
    # `rtl` stays here: it is a presentation concern derived from the ISO 15924
    # script column, and the directory's other consumers don't need it.
    infos = [
        LanguageInfo(
            code=row.code, name=row.name, nativeName=row.native_name,
            script=row.script, rtl=row.script in _RTL_SCRIPTS,
        )
        for row in visible_languages(db)
    ]
    return ([i for i in infos if i.code == "en"]
            + [i for i in infos if i.code != "en"])