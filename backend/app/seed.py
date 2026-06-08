from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.generated_name import (
    GeneratedName,
    GenerationFlavorModel,
    Language,
    NamePart,
)


def get_or_create_language(db, name: str) -> Language:
    language = db.scalar(
        select(Language).where(Language.name == name)
    )

    if language is None:
        language = Language(name=name)
        db.add(language)

    return language


def get_or_create_flavor(db, name: str) -> GenerationFlavorModel:
    flavor = db.scalar(
        select(GenerationFlavorModel).where(
            GenerationFlavorModel.name == name
        )
    )

    if flavor is None:
        flavor = GenerationFlavorModel(name=name)
        db.add(flavor)

    return flavor


def seed_database():
    db = SessionLocal()

    try:
        existing_name = db.scalar(
            select(GeneratedName).where(
                GeneratedName.slug == "auravel"
            )
        )

        if existing_name is not None:
            print("Seed data already exists.")
            return

        latin = get_or_create_language(db, "Latin")
        greek = get_or_create_language(db, "Greek")

        default = get_or_create_flavor(db, "default")
        fantasy = get_or_create_flavor(db, "fantasy")
        ancient = get_or_create_flavor(db, "ancient-inspired")
        modern = get_or_create_flavor(db, "modern")

        auravel = GeneratedName(
            slug="auravel",
            name="Auravel",
            meaning="Dawn and openness",
            explanation=(
                "A newly crafted name combining imagery of dawn "
                "with a light, open-sounding ending."
            ),
            source_languages=[latin],
            flavors=[default, fantasy, ancient],
            parts=[
                NamePart(
                    position=1,
                    text="aur-",
                    meaning="Dawn, glow, or golden light",
                    language="Latin-inspired",
                    kind="inspired",
                    note="Inspired by words such as aurora.",
                ),
                NamePart(
                    position=2,
                    text="-avel",
                    meaning="Open, airy, flowing sound",
                    language="Crafted",
                    kind="crafted",
                    note="An invented ending added for style and rhythm.",
                ),
            ],
        )

        lucira = GeneratedName(
            slug="lucira",
            name="Lucira",
            meaning="Light and clarity",
            explanation=(
                "A newly crafted name built around a root "
                "associated with light."
            ),
            source_languages=[latin],
            flavors=[default, fantasy, modern],
            parts=[
                NamePart(
                    position=1,
                    text="luc-",
                    meaning="Light or brightness",
                    language="Latin",
                    kind="root",
                    note="Related to the Latin word lux.",
                ),
                NamePart(
                    position=2,
                    text="-ira",
                    meaning="Soft, name-like ending",
                    language="Crafted",
                    kind="crafted",
                    note="An invented ending added for rhythm.",
                ),
            ],
        )

        photel = GeneratedName(
            slug="photel",
            name="Photel",
            meaning="Light",
            explanation=(
                "A compact generated name built around "
                "a Greek root associated with light."
            ),
            source_languages=[greek],
            flavors=[ancient],
            parts=[
                NamePart(
                    position=1,
                    text="phot-",
                    meaning="Light",
                    language="Greek",
                    kind="root",
                    note="Connected to Greek-derived words associated with light.",
                ),
                NamePart(
                    position=2,
                    text="-el",
                    meaning="Compact name-like ending",
                    language="Crafted",
                    kind="crafted",
                    note="An invented ending added for rhythm.",
                ),
            ],
        )

        db.add_all([auravel, lucira, photel])
        db.commit()

        print("Seed data inserted successfully.")

    finally:
        db.close()


if __name__ == "__main__":
    seed_database()