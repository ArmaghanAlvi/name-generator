from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.generated_name import (
    GeneratedName,
    GenerationFlavorModel,
    Language,
)
from app.schemas.generate import (
    GenerateRequest,
    GeneratedNameResponse,
    GenerationFlavor,
    NamePartKind,
    NamePartResponse,
)


def search_generated_names(
    db: Session,
    request: GenerateRequest,
) -> list[GeneratedNameResponse]:
    statement = (
        select(GeneratedName)
        .options(
            selectinload(GeneratedName.source_languages),
            selectinload(GeneratedName.flavors),
            selectinload(GeneratedName.parts),
        )
        .join(GeneratedName.flavors)
        .where(GenerationFlavorModel.name == request.flavor)
    )

    if request.language is not None:
        statement = (
            statement
            .join(GeneratedName.source_languages)
            .where(Language.name == request.language)
        )

    generated_names = db.scalars(statement).unique().all()

    return [
        GeneratedNameResponse(
            id=result.slug,
            name=result.name,
            category="generated",
            meaning=result.meaning,
            language="Generated",
            explanation=result.explanation,
            sourceLanguages=[
                language.name
                for language in result.source_languages
            ],
            flavors=[
                cast(GenerationFlavor, flavor.name)
                for flavor in result.flavors
            ],
            parts=[
                NamePartResponse(
                    text=part.text,
                    meaning=part.meaning,
                    language=part.language,
                    kind=cast(NamePartKind, part.kind),
                    note=part.note,
                )
                for part in result.parts
            ],
        )
        for result in generated_names
        if request.minLength <= len(result.name) <= request.maxLength
    ]