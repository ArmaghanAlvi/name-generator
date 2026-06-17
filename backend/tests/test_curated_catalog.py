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
from app.extractors.export_reviewed_oewn_yellow import (
    export_reviewed_oewn_yellow,
)

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "curated"
    / "v4"
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
            "xx,mystery-word,,noun,,"
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


def test_light_expansion_returns_top_three_related_concepts(
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
        "brightness",
        "radiance",
        "clarity",
    ]

    assert any(
        result.name == "brightness"
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
            "en,malformed,,noun,,"
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
            "en,mystery-word,,noun,,"
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


def test_export_reviewed_oewn_yellow_only_exports_reviewed_rows(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base"
    out = tmp_path / "out"
    candidates = tmp_path / "candidates"

    copytree(
        CATALOG_PATH,
        base,
    )

    candidates.mkdir()

    (
        candidates / "candidate_concepts.csv"
    ).write_text(
        "\n".join(
            [
                (
                    "slug,label,description,domain,status,"
                    "concept_type,is_public,external_source_slug,"
                    "external_concept_id,review_status,decision,"
                    "target_concept_slug,notes"
                ),
                (
                    "gleam,Gleam,a small flash of light,"
                    "light_and_sky,active,external_synset,true,"
                    "oewn-2025,oewn-test-gleam,reviewed,"
                    "accept,,"
                ),
                (
                    "wrong,Wrong,not reviewed,"
                    "test,active,external_synset,true,"
                    "oewn-2025,oewn-test-wrong,pending_review,"
                    ",,"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (
        candidates / "candidate_concept_relationships.csv"
    ).write_text(
        "\n".join(
            [
                (
                    "source_concept_slug,target_concept_slug,"
                    "relationship_type,weight,source_slug,"
                    "source_locator,confidence,review_status"
                ),
                (
                    "illumination,gleam,near_synonym,0.80,"
                    "oewn-2025,oewn-test-rel,medium,reviewed"
                ),
                (
                    "illumination,wrong,near_synonym,0.80,"
                    "oewn-2025,oewn-test-rel-wrong,"
                    "medium,pending_review"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (
        candidates / "candidate_concept_mappings.csv"
    ).write_text(
        "\n".join(
            [
                (
                    "source_concept_slug,target_concept_slug,"
                    "mapping_type,weight,source_slug,"
                    "source_locator,confidence,review_status"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (
        candidates / "candidate_words.csv"
    ).write_text(
        "\n".join(
            [
                (
                    "language_code,text,transliteration,"
                    "part_of_speech,external_entry_id,notes,"
                    "source_slug,review_status"
                ),
                (
                    "en,gleam,,noun,oewn-gleam,"
                    "Imported from Open English Wordnet.,"
                    "oewn-2025,reviewed"
                ),
                (
                    "en,wrong,,noun,oewn-wrong,"
                    "Not reviewed.,"
                    "oewn-2025,pending_review"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (
        candidates / "candidate_word_senses.csv"
    ).write_text(
        "\n".join(
            [
                (
                    "language_code,word_text,part_of_speech,"
                    "concept_slug,gloss,is_primary,"
                    "equivalence_type,sense_rank,"
                    "external_sense_id,external_synset_id,"
                    "source_slug,source_locator,confidence,"
                    "review_status"
                ),
                (
                    "en,gleam,noun,gleam,"
                    "a small flash of light,true,"
                    "canonical,1,oewn-gleam-sense,"
                    "oewn-test-gleam,oewn-2025,"
                    "oewn-test-gleam#sense,medium,reviewed"
                ),
                (
                    "en,wrong,noun,wrong,"
                    "not reviewed,true,"
                    "canonical,1,oewn-wrong-sense,"
                    "oewn-test-wrong,oewn-2025,"
                    "oewn-test-wrong#sense,medium,pending_review"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    added = export_reviewed_oewn_yellow(
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

    concepts = (
        out / "concepts.csv"
    ).read_text(
        encoding="utf-8"
    )

    relationships = (
        out / "concept_relationships.csv"
    ).read_text(
        encoding="utf-8"
    )

    assert added["concepts"] == 1
    assert added["words"] == 1
    assert added["word_senses"] == 1
    assert added["concept_relationships"] == 1

    assert "gleam" in concepts
    assert "gleam" in words
    assert "gleam" in senses
    assert "illumination,gleam" in relationships

    assert "wrong" not in concepts
    assert "wrong" not in words
    assert "wrong" not in senses
    assert "illumination,wrong" not in relationships


def test_light_zero_expansion_returns_light_not_brightness(
    db: Session,
) -> None:
    import_catalog(db, CATALOG_PATH)

    response = explore_meanings(
        db,
        ExploreRequest(
            meanings=["light"],
            expansionCount=0,
            language="English",
            minLength=0,
            maxLength=30,
        ),
    )

    yellow_names = [
        result.name
        for result in response.results
        if result.category == "translation"
    ]

    assert "light" in yellow_names
    assert "brightness" not in yellow_names


def test_brightness_zero_expansion_returns_brightness_not_light(
    db: Session,
) -> None:
    import_catalog(db, CATALOG_PATH)

    response = explore_meanings(
        db,
        ExploreRequest(
            meanings=["brightness"],
            expansionCount=0,
            language="English",
            minLength=0,
            maxLength=30,
        ),
    )

    yellow_names = [
        result.name
        for result in response.results
        if result.category == "translation"
    ]

    assert "brightness" in yellow_names
    assert "light" not in yellow_names


def test_light_expansion_returns_related_brightness(
    db: Session,
) -> None:
    import_catalog(db, CATALOG_PATH)

    response = explore_meanings(
        db,
        ExploreRequest(
            meanings=["light"],
            expansionCount=1,
            language="English",
            minLength=0,
            maxLength=30,
        ),
    )

    yellow_names = [
        result.name
        for result in response.results
        if result.category == "translation"
    ]

    assert "light" in yellow_names
    assert "brightness" in yellow_names


def test_brightness_expansion_returns_related_light(
    db: Session,
) -> None:
    import_catalog(db, CATALOG_PATH)

    response = explore_meanings(
        db,
        ExploreRequest(
            meanings=["brightness"],
            expansionCount=1,
            language="English",
            minLength=0,
            maxLength=30,
        ),
    )

    yellow_names = [
        result.name
        for result in response.results
        if result.category == "translation"
    ]

    assert "brightness" in yellow_names
    assert "light" in yellow_names