from pathlib import Path
from shutil import copytree

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.importers.curated_catalog import import_catalog
from app.importers.validators import CatalogValidationError
from app.models.generated_name import Language
from app.models.semantic import (
    Concept,
    ConceptAlias,
    Source,
    Word,
    WordSense,
)
from app.schemas.explore import ExploreRequest
from app.services.semantic_search import explore_meanings


CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "curated"
    / "v0"
)


def count(
    db: Session,
    model: type,
) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(model)
        )
        or 0
    )


def test_dry_run_rolls_back_all_rows(
    db: Session,
) -> None:
    report = import_catalog(
        db,
        CATALOG_PATH,
        dry_run=True,
    )

    assert report.dry_run is True
    assert count(db, Source) == 0
    assert count(db, Language) == 0
    assert count(db, Concept) == 0
    assert count(db, Word) == 0
    assert count(db, WordSense) == 0


def test_import_is_idempotent(
    db: Session,
) -> None:
    import_catalog(
        db,
        CATALOG_PATH,
    )

    first_counts = {
        "sources": count(db, Source),
        "languages": count(db, Language),
        "concepts": count(db, Concept),
        "aliases": count(db, ConceptAlias),
        "words": count(db, Word),
        "word_senses": count(db, WordSense),
    }

    second_report = import_catalog(
        db,
        CATALOG_PATH,
    )

    second_counts = {
        "sources": count(db, Source),
        "languages": count(db, Language),
        "concepts": count(db, Concept),
        "aliases": count(db, ConceptAlias),
        "words": count(db, Word),
        "word_senses": count(db, WordSense),
    }

    assert second_counts == first_counts
    assert sum(
        second_report.inserted.values()
    ) == 0


def test_unknown_language_code_is_rejected(
    db: Session,
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "catalog"

    copytree(
        CATALOG_PATH,
        catalog,
    )

    with (
        catalog / "words.csv"
    ).open(
        "a",
        encoding="utf-8",
        newline="",
    ) as file:
        file.write(
            "\n"
            "xx,mystery-word,,noun,"
            "Invalid test row.,"
            "vertical-slice-demo\n"
        )

    with pytest.raises(
        CatalogValidationError,
        match="unknown language code 'xx'",
    ):
        import_catalog(
            db,
            catalog,
        )


def test_invalid_relationship_weight_is_rejected(
    db: Session,
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "catalog"

    copytree(
        CATALOG_PATH,
        catalog,
    )

    path = (
        catalog
        / "concept_relationships.csv"
    )

    text = path.read_text(
        encoding="utf-8"
    )

    path.write_text(
        text.replace(
            "0.95",
            "1.25",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        CatalogValidationError,
        match="weight must be between 0 and 1",
    ):
        import_catalog(
            db,
            catalog,
        )


def test_light_query_returns_imported_yellow_cards(
    db: Session,
) -> None:
    import_catalog(
        db,
        CATALOG_PATH,
    )

    response = explore_meanings(
        db,
        ExploreRequest(
            meanings=["light"],
            expansionCount=0,
            language=None,
            minLength=0,
            maxLength=30,
        ),
    )

    yellow_names = {
        result.name
        for result in response.results
        if result.category == "translation"
    }

    assert "light" in yellow_names
    assert "lux" in yellow_names
    assert "φῶς (phōs)" in yellow_names
    assert "نور (nūr)" in yellow_names
    assert "光 (hikari)" in yellow_names


def test_light_expansion_adds_dawn_after_three_expansions(
    db: Session,
) -> None:
    import_catalog(
        db,
        CATALOG_PATH,
    )

    response = explore_meanings(
        db,
        ExploreRequest(
            meanings=["light"],
            expansionCount=3,
            language="English",
            minLength=0,
            maxLength=30,
        ),
    )

    assert [
        concept.slug
        for concept in response.expandedConcepts
    ] == [
        "radiance",
        "clarity",
        "dawn",
    ]

    assert any(
        result.name == "dawn"
        and result.matchType == "expanded"
        for result in response.results
    )