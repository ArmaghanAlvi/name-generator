"""
GET /languages -- the imported-language directory (Breakdown 5).

DB-derived exactly like the interleave order (Breakdown 4, Step 1d): every
language with visible senses, ascending language id, English pinned first.
`rtl` is computed from the ISO 15924 script column so future RTL languages
(he, fa) are correct at import time with zero frontend changes.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.generated_name import Language
from app.models.semantic import Lexeme, Sense

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
    rows = db.execute(
        select(Language.code, Language.name, Language.native_name,
               Language.script)
        .join(Lexeme, Lexeme.language_id == Language.id)
        .join(Sense, Sense.lexeme_id == Lexeme.id)
        .where(Sense.visibility_status == "visible",
               Language.code.isnot(None))
        .group_by(Language.id)
        .order_by(Language.id)
    ).all()
    infos = [
        LanguageInfo(
            code=code, name=name, nativeName=native,
            script=script, rtl=script in _RTL_SCRIPTS,
        )
        for (code, name, native, script) in rows
    ]
    return ([i for i in infos if i.code == "en"]
            + [i for i in infos if i.code != "en"])