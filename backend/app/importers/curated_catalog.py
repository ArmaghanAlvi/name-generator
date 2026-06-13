from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.importers.validators import (
    CONFIDENCE_VALUES,
    CONCEPT_STATUS_VALUES,
    RELATIONSHIP_TYPE_VALUES,
    REVIEW_STATUS_VALUES,
    CatalogValidationError,
    ensure_unique_rows,
    optional,
    parse_bool,
    parse_weight,
    require,
    require_choice,
)
from app.models.generated_name import Language
from app.models.semantic import (
    Concept,
    ConceptAlias,
    ConceptRelationship,
    Source,
    Word,
    WordSense,
)
from app.utils.text import normalize_text


@dataclass
class ImportReport:
    inserted: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    updated: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    unchanged: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    dry_run: bool = False

    def mark(
        self,
        table: str,
        outcome: str,
    ) -> None:
        getattr(self, outcome)[table] += 1

    def render(self) -> str:
        if self.dry_run:
            lines = [
                "DRY RUN: database changes were rolled back."
            ]
        else:
            lines = [
                "IMPORT COMPLETE"
            ]

        tables = sorted(
            set(self.inserted)
            | set(self.updated)
            | set(self.unchanged)
        )

        for table in tables:
            lines.append(
                f"{table}: "
                f"inserted={self.inserted[table]}, "
                f"updated={self.updated[table]}, "
                f"unchanged={self.unchanged[table]}"
            )

        return "\n".join(lines)


FILE_COLUMNS: dict[str, set[str]] = {
    "sources.csv": {
        "slug",
        "name",
        "source_type",
        "url",
        "license",
        "notes",
    },
    "languages.csv": {
        "code",
        "name",
        "native_name",
        "script",
    },
    "concepts.csv": {
        "slug",
        "label",
        "description",
        "domain",
        "status",
    },
    "concept_aliases.csv": {
        "concept_slug",
        "text",
    },
    "concept_relationships.csv": {
        "source_concept_slug",
        "target_concept_slug",
        "relationship_type",
        "weight",
        "source_slug",
        "source_locator",
        "confidence",
        "review_status",
    },
    "words.csv": {
        "language_code",
        "text",
        "transliteration",
        "part_of_speech",
        "notes",
        "source_slug",
    },
    "word_senses.csv": {
        "language_code",
        "word_text",
        "concept_slug",
        "gloss",
        "is_primary",
        "source_slug",
        "source_locator",
        "confidence",
        "review_status",
    },
}


def read_rows(
    path: Path,
    required_columns: set[str],
) -> list[tuple[int, dict[str, str]]]:
    if not path.exists():
        raise CatalogValidationError(
            f"Missing required file: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = set(reader.fieldnames or [])

        missing = required_columns - fieldnames

        if missing:
            columns = ", ".join(sorted(missing))

            raise CatalogValidationError(
                f"{path.name}: missing columns: {columns}"
            )

        rows: list[tuple[int, dict[str, str]]] = []

        for line, raw_row in enumerate(reader, start=2):
            # DictReader stores extra CSV values under a None key.
            # This usually means that the row has too many commas
            # or two rows were accidentally joined together.
            extra_values = raw_row.get(None)

            if extra_values:
                raise CatalogValidationError(
                    f"{path.name}:{line}: "
                    "row contains more values than the header defines. "
                    "Check for an extra comma or a missing newline."
                )

            row = {
                key: (value or "").strip()
                for key, value in raw_row.items()
                if key is not None
            }

            if any(row.values()):
                rows.append((line, row))

        return rows


def load_files(
    catalog_path: Path,
) -> dict[str, list[tuple[int, dict[str, str]]]]:
    return {
        filename: read_rows(
            catalog_path / filename,
            columns,
        )
        for filename, columns in FILE_COLUMNS.items()
    }


def source_by_slug(
    db: Session,
    slug: str,
    *,
    file: Path,
    line: int,
) -> Source:
    source = db.scalar(
        select(Source).where(
            Source.slug == slug
        )
    )

    if source is None:
        raise CatalogValidationError(
            f"{file.name}:{line}: "
            f"unknown source slug '{slug}'"
        )

    return source


def language_by_code(
    db: Session,
    code: str,
    *,
    file: Path,
    line: int,
) -> Language:
    language = db.scalar(
        select(Language).where(
            Language.code == code
        )
    )

    if language is None:
        raise CatalogValidationError(
            f"{file.name}:{line}: "
            f"unknown language code '{code}'"
        )

    return language


def concept_by_slug(
    db: Session,
    slug: str,
    *,
    file: Path,
    line: int,
) -> Concept:
    concept = db.scalar(
        select(Concept).where(
            Concept.slug == slug
        )
    )

    if concept is None:
        raise CatalogValidationError(
            f"{file.name}:{line}: "
            f"unknown concept slug '{slug}'"
        )

    return concept


def apply_values(
    obj: object,
    values: dict[str, object],
) -> bool:
    changed = False

    for key, value in values.items():
        if getattr(obj, key) != value:
            setattr(obj, key, value)
            changed = True

    return changed


def mark_existing(
    report: ImportReport,
    table: str,
    changed: bool,
) -> None:
    if changed:
        report.mark(table, "updated")
    else:
        report.mark(table, "unchanged")


def import_sources(
    db: Session,
    rows: list[tuple[int, dict[str, str]]],
    report: ImportReport,
    file: Path,
) -> None:
    ensure_unique_rows(
        rows,
        file=file,
        key_fields=("slug",),
    )

    for line, row in rows:
        slug = require(
            row,
            "slug",
            file=file,
            line=line,
        )

        values = {
            "name": require(
                row,
                "name",
                file=file,
                line=line,
            ),
            "source_type": require(
                row,
                "source_type",
                file=file,
                line=line,
            ),
            "url": optional(row, "url"),
            "license": optional(row, "license"),
            "notes": optional(row, "notes"),
        }

        source = db.scalar(
            select(Source).where(
                Source.slug == slug
            )
        )

        if source is None:
            db.add(
                Source(
                    slug=slug,
                    **values,
                )
            )
            report.mark("sources", "inserted")
        else:
            mark_existing(
                report,
                "sources",
                apply_values(source, values),
            )

    db.flush()


def import_languages(
    db: Session,
    rows: list[tuple[int, dict[str, str]]],
    report: ImportReport,
    file: Path,
) -> None:
    ensure_unique_rows(
        rows,
        file=file,
        key_fields=("code",),
    )

    for line, row in rows:
        code = require(
            row,
            "code",
            file=file,
            line=line,
        ).casefold()

        name = require(
            row,
            "name",
            file=file,
            line=line,
        )

        values = {
            "name": name,
            "native_name": optional(row, "native_name"),
            "script": optional(row, "script"),
        }

        language = db.scalar(
            select(Language).where(
                Language.code == code
            )
        )

        if language is None:
            # Reuse an existing seed row if it has the same
            # name but has not received a code yet.
            language = db.scalar(
                select(Language).where(
                    Language.name == name,
                    Language.code.is_(None),
                )
            )

        if language is None:
            db.add(
                Language(
                    code=code,
                    **values,
                )
            )
            report.mark("languages", "inserted")
        else:
            changed = apply_values(
                language,
                {
                    "code": code,
                    **values,
                },
            )

            mark_existing(
                report,
                "languages",
                changed,
            )

    db.flush()


def import_concepts(
    db: Session,
    rows: list[tuple[int, dict[str, str]]],
    report: ImportReport,
    file: Path,
) -> None:
    ensure_unique_rows(
        rows,
        file=file,
        key_fields=("slug",),
    )

    for line, row in rows:
        slug = require(
            row,
            "slug",
            file=file,
            line=line,
        )

        status = require_choice(
            require(
                row,
                "status",
                file=file,
                line=line,
            ),
            CONCEPT_STATUS_VALUES,
            file=file,
            line=line,
            field="status",
        )

        values = {
            "label": require(
                row,
                "label",
                file=file,
                line=line,
            ),
            "description": optional(row, "description"),
            "domain": optional(row, "domain"),
            "status": status,
        }

        concept = db.scalar(
            select(Concept).where(
                Concept.slug == slug
            )
        )

        if concept is None:
            db.add(
                Concept(
                    slug=slug,
                    **values,
                )
            )
            report.mark("concepts", "inserted")
        else:
            mark_existing(
                report,
                "concepts",
                apply_values(concept, values),
            )

    db.flush()


def import_aliases(
    db: Session,
    rows: list[tuple[int, dict[str, str]]],
    report: ImportReport,
    file: Path,
) -> None:
    ensure_unique_rows(
        rows,
        file=file,
        key_fields=(
            "concept_slug",
            "text",
        ),
    )

    for line, row in rows:
        concept = concept_by_slug(
            db,
            require(
                row,
                "concept_slug",
                file=file,
                line=line,
            ),
            file=file,
            line=line,
        )

        text = require(
            row,
            "text",
            file=file,
            line=line,
        )

        normalized = normalize_text(text)

        alias = db.scalar(
            select(ConceptAlias).where(
                ConceptAlias.concept_id == concept.id,
                ConceptAlias.normalized_text == normalized,
            )
        )

        if alias is None:
            db.add(
                ConceptAlias(
                    concept=concept,
                    text=text,
                    normalized_text=normalized,
                )
            )
            report.mark("concept_aliases", "inserted")
        else:
            mark_existing(
                report,
                "concept_aliases",
                apply_values(
                    alias,
                    {
                        "text": text,
                    },
                ),
            )

    db.flush()


def import_relationships(
    db: Session,
    rows: list[tuple[int, dict[str, str]]],
    report: ImportReport,
    file: Path,
) -> None:
    ensure_unique_rows(
        rows,
        file=file,
        key_fields=(
            "source_concept_slug",
            "target_concept_slug",
            "relationship_type",
        ),
    )

    for line, row in rows:
        source_concept = concept_by_slug(
            db,
            require(
                row,
                "source_concept_slug",
                file=file,
                line=line,
            ),
            file=file,
            line=line,
        )

        target_concept = concept_by_slug(
            db,
            require(
                row,
                "target_concept_slug",
                file=file,
                line=line,
            ),
            file=file,
            line=line,
        )

        relationship_type = require_choice(
            require(
                row,
                "relationship_type",
                file=file,
                line=line,
            ),
            RELATIONSHIP_TYPE_VALUES,
            file=file,
            line=line,
            field="relationship_type",
        )

        values = {
            "weight": parse_weight(
                require(
                    row,
                    "weight",
                    file=file,
                    line=line,
                ),
                file=file,
                line=line,
            ),
            "source": source_by_slug(
                db,
                require(
                    row,
                    "source_slug",
                    file=file,
                    line=line,
                ),
                file=file,
                line=line,
            ),
            "source_locator": optional(
                row,
                "source_locator",
            ),
            "confidence": require_choice(
                require(
                    row,
                    "confidence",
                    file=file,
                    line=line,
                ),
                CONFIDENCE_VALUES,
                file=file,
                line=line,
                field="confidence",
            ),
            "review_status": require_choice(
                require(
                    row,
                    "review_status",
                    file=file,
                    line=line,
                ),
                REVIEW_STATUS_VALUES,
                file=file,
                line=line,
                field="review_status",
            ),
        }

        relationship = db.scalar(
            select(ConceptRelationship).where(
                ConceptRelationship.source_concept_id
                == source_concept.id,
                ConceptRelationship.target_concept_id
                == target_concept.id,
                ConceptRelationship.relationship_type
                == relationship_type,
            )
        )

        if relationship is None:
            db.add(
                ConceptRelationship(
                    source_concept=source_concept,
                    target_concept=target_concept,
                    relationship_type=relationship_type,
                    **values,
                )
            )
            report.mark(
                "concept_relationships",
                "inserted",
            )
        else:
            mark_existing(
                report,
                "concept_relationships",
                apply_values(
                    relationship,
                    values,
                ),
            )

    db.flush()


def import_words(
    db: Session,
    rows: list[tuple[int, dict[str, str]]],
    report: ImportReport,
    file: Path,
) -> None:
    ensure_unique_rows(
        rows,
        file=file,
        key_fields=(
            "language_code",
            "text",
        ),
    )

    for line, row in rows:
        language = language_by_code(
            db,
            require(
                row,
                "language_code",
                file=file,
                line=line,
            ).casefold(),
            file=file,
            line=line,
        )

        text = require(
            row,
            "text",
            file=file,
            line=line,
        )

        normalized = normalize_text(text)

        values = {
            "text": text,
            "transliteration": optional(
                row,
                "transliteration",
            ),
            "part_of_speech": optional(
                row,
                "part_of_speech",
            ),
            "notes": optional(
                row,
                "notes",
            ),
            "source": source_by_slug(
                db,
                require(
                    row,
                    "source_slug",
                    file=file,
                    line=line,
                ),
                file=file,
                line=line,
            ),
        }

        word = db.scalar(
            select(Word).where(
                Word.language_id == language.id,
                Word.normalized_text == normalized,
            )
        )

        if word is None:
            db.add(
                Word(
                    language=language,
                    normalized_text=normalized,
                    **values,
                )
            )
            report.mark("words", "inserted")
        else:
            mark_existing(
                report,
                "words",
                apply_values(word, values),
            )

    db.flush()


def import_word_senses(
    db: Session,
    rows: list[tuple[int, dict[str, str]]],
    report: ImportReport,
    file: Path,
) -> None:
    ensure_unique_rows(
        rows,
        file=file,
        key_fields=(
            "language_code",
            "word_text",
            "concept_slug",
        ),
    )

    for line, row in rows:
        language = language_by_code(
            db,
            require(
                row,
                "language_code",
                file=file,
                line=line,
            ).casefold(),
            file=file,
            line=line,
        )

        word_text = require(
            row,
            "word_text",
            file=file,
            line=line,
        )

        word = db.scalar(
            select(Word).where(
                Word.language_id == language.id,
                Word.normalized_text
                == normalize_text(word_text),
            )
        )

        if word is None:
            raise CatalogValidationError(
                f"{file.name}:{line}: "
                f"unknown word '{word_text}' "
                f"for language '{language.code}'"
            )

        concept = concept_by_slug(
            db,
            require(
                row,
                "concept_slug",
                file=file,
                line=line,
            ),
            file=file,
            line=line,
        )

        values = {
            "gloss": require(
                row,
                "gloss",
                file=file,
                line=line,
            ),
            "is_primary": parse_bool(
                require(
                    row,
                    "is_primary",
                    file=file,
                    line=line,
                ),
                file=file,
                line=line,
                field="is_primary",
            ),
            "source": source_by_slug(
                db,
                require(
                    row,
                    "source_slug",
                    file=file,
                    line=line,
                ),
                file=file,
                line=line,
            ),
            "source_locator": optional(
                row,
                "source_locator",
            ),
            "confidence": require_choice(
                require(
                    row,
                    "confidence",
                    file=file,
                    line=line,
                ),
                CONFIDENCE_VALUES,
                file=file,
                line=line,
                field="confidence",
            ),
            "review_status": require_choice(
                require(
                    row,
                    "review_status",
                    file=file,
                    line=line,
                ),
                REVIEW_STATUS_VALUES,
                file=file,
                line=line,
                field="review_status",
            ),
        }

        sense = db.scalar(
            select(WordSense).where(
                WordSense.word_id == word.id,
                WordSense.concept_id == concept.id,
            )
        )

        if sense is None:
            db.add(
                WordSense(
                    word=word,
                    concept=concept,
                    **values,
                )
            )
            report.mark("word_senses", "inserted")
        else:
            mark_existing(
                report,
                "word_senses",
                apply_values(sense, values),
            )

    db.flush()


def import_catalog(
    db: Session,
    catalog_path: Path,
    *,
    dry_run: bool = False,
) -> ImportReport:
    files = load_files(catalog_path)
    report = ImportReport(dry_run=dry_run)

    try:
        import_sources(
            db,
            files["sources.csv"],
            report,
            catalog_path / "sources.csv",
        )

        import_languages(
            db,
            files["languages.csv"],
            report,
            catalog_path / "languages.csv",
        )

        import_concepts(
            db,
            files["concepts.csv"],
            report,
            catalog_path / "concepts.csv",
        )

        import_aliases(
            db,
            files["concept_aliases.csv"],
            report,
            catalog_path / "concept_aliases.csv",
        )

        import_relationships(
            db,
            files["concept_relationships.csv"],
            report,
            catalog_path / "concept_relationships.csv",
        )

        import_words(
            db,
            files["words.csv"],
            report,
            catalog_path / "words.csv",
        )

        import_word_senses(
            db,
            files["word_senses.csv"],
            report,
            catalog_path / "word_senses.csv",
        )

        if dry_run:
            db.rollback()
        else:
            db.commit()

        return report

    except Exception:
        db.rollback()
        raise


def main() -> None:
    # Import this lazily so unit tests can inject an isolated
    # database session without loading a real DATABASE_URL.
    from app.db.session import SessionLocal

    parser = argparse.ArgumentParser(
        description=(
            "Import a curated semantic catalog "
            "into PostgreSQL."
        )
    )

    parser.add_argument(
        "--path",
        type=Path,
        required=True,
        help="Directory containing curated CSV files.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Validate and report changes, "
            "then roll back the transaction."
        ),
    )

    args = parser.parse_args()

    with SessionLocal() as db:
        report = import_catalog(
            db,
            args.path,
            dry_run=args.dry_run,
        )

    print(report.render())


if __name__ == "__main__":
    main()


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