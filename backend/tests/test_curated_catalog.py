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
from app.extractors.export_reviewed_yellow import export_reviewed

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


def test_extra_csv_columns_are_rejected(
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
            "en,malformed,,noun,"
            "Test row.,vertical-slice-demo,"
            "unexpected-extra-value\n"
        )

    with pytest.raises(
        CatalogValidationError,
        match="row contains more values than the header defines",
    ):
        import_catalog(
            db,
            catalog,
        )


def test_unknown_source_slug_is_rejected(
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
            "en,mystery-word,,noun,"
            "Invalid test row.,"
            "unknown-source\n"
        )

    with pytest.raises(
        CatalogValidationError,
        match="unknown source slug 'unknown-source'",
    ):
        import_catalog(
            db,
            catalog,
        )


def test_missing_required_csv_file_is_rejected(
    db: Session,
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "catalog"

    copytree(
        CATALOG_PATH,
        catalog,
    )

    (
        catalog / "words.csv"
    ).unlink()

    with pytest.raises(
        CatalogValidationError,
        match="Missing required file",
    ):
        import_catalog(
            db,
            catalog,
        )


def test_missing_required_column_is_rejected(
    db: Session,
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "catalog"

    copytree(
        CATALOG_PATH,
        catalog,
    )

    path = catalog / "words.csv"

    lines = path.read_text(
        encoding="utf-8"
    ).splitlines()

    header = lines[0].split(",")

    source_slug_index = header.index("source_slug")
    header.pop(source_slug_index)

    new_lines = [
        ",".join(header),
        *lines[1:],
    ]

    path.write_text(
        "\n".join(new_lines) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        CatalogValidationError,
        match="missing columns: source_slug",
    ):
        import_catalog(
            db,
            catalog,
        )


def test_duplicate_concept_slug_is_rejected(
    db: Session,
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "catalog"

    copytree(
        CATALOG_PATH,
        catalog,
    )

    concepts_path = catalog / "concepts.csv"

    lines = concepts_path.read_text(
        encoding="utf-8"
    ).splitlines()

    first_data_row = lines[1]

    with concepts_path.open(
        "a",
        encoding="utf-8",
        newline="",
    ) as file:
        file.write(
            "\n" + first_data_row
        )

    with pytest.raises(
        CatalogValidationError,
        match="duplicate",
    ):
        import_catalog(
            db,
            catalog,
        )


def test_invalid_review_status_is_rejected(
    db: Session,
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "catalog"

    copytree(
        CATALOG_PATH,
        catalog,
    )

    path = catalog / "word_senses.csv"

    text = path.read_text(
        encoding="utf-8"
    )

    path.write_text(
        text.replace(
            "reviewed",
            "maybe-reviewed",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        CatalogValidationError,
        match="review_status",
    ):
        import_catalog(
            db,
            catalog,
        )


def test_export_reviewed_yellow_only_exports_reviewed_rows(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base"
    out = tmp_path / "out"
    candidates = tmp_path / "candidate_word_senses.csv"

    copytree(
        CATALOG_PATH,
        base,
    )

    candidates.write_text(
        "\n".join(
            [
                (
                    "source_slug,language_code,word_text,"
                    "part_of_speech,concept_slug,gloss,"
                    "match_method,match_confidence,source_locator,"
                    "review_status,notes"
                ),
                (
                    "oewn-2025,en,gleam,n,illumination,"
                    "a flash of light,lemma_alias,0.98,"
                    "ewn-test#sense-1,reviewed,"
                ),
                (
                    "oewn-2025,en,wrong,n,illumination,"
                    "not reviewed,lemma_alias,0.98,"
                    "ewn-test#sense-2,pending_review,"
                ),
            ]
        ),
        encoding="utf-8",
    )

    export_reviewed(
        base_path=base,
        candidates_path=candidates,
        output_path=out,
        replace=True,
    )

    words = (
        out / "words.csv"
    ).read_text(
        encoding="utf-8"
    )

    senses = (
        out / "word_senses.csv"
    ).read_text(
        encoding="utf-8"
    )

    assert "gleam" in words
    assert "gleam" in senses
    assert "wrong" not in words
    assert "wrong" not in senses