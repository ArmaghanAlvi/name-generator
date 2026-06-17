from __future__ import annotations

import argparse
import csv
import shutil
import sqlite3
from pathlib import Path

from app.review.constants import (
    CONCEPT_COLUMNS,
    MAPPING_COLUMNS,
    RELATIONSHIP_COLUMNS,
    REVIEW_STATUSES,
    WORD_COLUMNS,
    WORD_SENSE_COLUMNS,
)
from app.utils.text import normalize_text


TECHNICAL_TERMS = {
    "unit",
    "measure",
    "measurement",
    "photometric",
    "physics",
    "chemical",
    "substance",
    "radiation",
    "electromagnetic",
    "instrument",
    "device",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)
        rows: list[dict[str, str]] = []

        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(
                    f"{path}:{line_number}: row contains more values "
                    "than the header defines"
                )

            cleaned = {
                key: (value or "").strip()
                for key, value in row.items()
            }

            if any(cleaned.values()):
                rows.append(cleaned)

        return rows


def normalize_status(value: str | None) -> str:
    status = (value or "").strip().casefold()

    if status in REVIEW_STATUSES:
        return status

    if status == "unreviewed":
        return "pending_review"

    return "pending_review"


def looks_technical(*values: str) -> bool:
    text = normalize_text(" ".join(values))

    return any(
        term in text
        for term in TECHNICAL_TERMS
    )


def preclassify_concept(row: dict[str, str]) -> tuple[str, int, str]:
    status = normalize_status(row.get("review_status"))

    if status != "pending_review":
        return status, 50, "existing_status"

    slug = row.get("slug", "")
    label = row.get("label", "")
    description = row.get("description", "")

    if not slug or not label:
        return "needs_edit", 95, "missing_slug_or_label"

    if looks_technical(slug, label, description):
        return "pending_review", 20, "likely_technical"

    if row.get("is_public", "").casefold() in {"true", "1", "yes"}:
        return "pending_review", 90, "public_searchable_candidate"

    return "pending_review", 60, "normal_candidate"


def preclassify_word(row: dict[str, str]) -> tuple[str, int, str]:
    status = normalize_status(row.get("review_status"))

    if status != "pending_review":
        return status, 50, "existing_status"

    if not row.get("text", "").strip():
        return "needs_edit", 95, "missing_word_text"

    if not row.get("part_of_speech", "").strip():
        return "needs_edit", 80, "missing_part_of_speech"

    if looks_technical(
        row.get("text", ""),
        row.get("notes", ""),
    ):
        return "pending_review", 20, "likely_technical"

    return "pending_review", 75, "normal_word_candidate"


def preclassify_word_sense(row: dict[str, str]) -> tuple[str, int, str]:
    status = normalize_status(row.get("review_status"))

    if status != "pending_review":
        return status, 50, "existing_status"

    required = [
        "word_text",
        "part_of_speech",
        "concept_slug",
        "gloss",
        "source_slug",
        "source_locator",
    ]

    if any(not row.get(field, "").strip() for field in required):
        return "needs_edit", 100, "missing_required_sense_field"

    word = normalize_text(row["word_text"])
    concept = normalize_text(
        row["concept_slug"].replace("_", " ")
    )

    if word and word in concept:
        return "pending_review", 95, "word_matches_concept"

    if looks_technical(
        row.get("word_text", ""),
        row.get("concept_slug", ""),
        row.get("gloss", ""),
    ):
        return "pending_review", 20, "likely_technical"

    confidence = row.get("confidence", "").casefold()

    if confidence == "high":
        return "pending_review", 85, "high_confidence"

    return "pending_review", 70, "normal_sense_candidate"


def preclassify_relationship(row: dict[str, str]) -> tuple[str, int, str]:
    status = normalize_status(row.get("review_status"))

    if status != "pending_review":
        return status, 50, "existing_status"

    try:
        weight = float(row.get("weight", "0"))
    except ValueError:
        return "needs_edit", 100, "invalid_weight"

    if weight < 0 or weight > 1:
        return "needs_edit", 100, "weight_out_of_range"

    if weight < 0.35:
        return "pending_review", 15, "weak_relationship"

    relationship_type = row.get(
        "relationship_type",
        "",
    ).casefold()

    if relationship_type in {"synonym", "near_synonym"}:
        return "pending_review", 90, "strong_lexical_relation"

    if relationship_type == "associated":
        return "pending_review", 65, "associated_relation"

    return "pending_review", 55, "normal_relationship_candidate"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS review_concepts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL,
            label TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            domain TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            concept_type TEXT NOT NULL DEFAULT 'external_synset',
            is_public TEXT NOT NULL DEFAULT 'true',
            external_source_slug TEXT NOT NULL DEFAULT '',
            external_concept_id TEXT NOT NULL DEFAULT '',
            review_status TEXT NOT NULL DEFAULT 'pending_review',
            decision TEXT NOT NULL DEFAULT '',
            target_concept_slug TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            priority INTEGER NOT NULL DEFAULT 50,
            review_reason TEXT NOT NULL DEFAULT '',
            UNIQUE(slug)
        );

        CREATE TABLE IF NOT EXISTS review_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            language_code TEXT NOT NULL,
            text TEXT NOT NULL,
            transliteration TEXT NOT NULL DEFAULT '',
            part_of_speech TEXT NOT NULL DEFAULT '',
            external_entry_id TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            source_slug TEXT NOT NULL DEFAULT '',
            review_status TEXT NOT NULL DEFAULT 'pending_review',
            priority INTEGER NOT NULL DEFAULT 50,
            review_reason TEXT NOT NULL DEFAULT '',
            UNIQUE(language_code, text, part_of_speech)
        );

        CREATE TABLE IF NOT EXISTS review_word_senses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            language_code TEXT NOT NULL,
            word_text TEXT NOT NULL,
            part_of_speech TEXT NOT NULL DEFAULT '',
            concept_slug TEXT NOT NULL,
            gloss TEXT NOT NULL DEFAULT '',
            is_primary TEXT NOT NULL DEFAULT 'true',
            equivalence_type TEXT NOT NULL DEFAULT 'canonical',
            sense_rank TEXT NOT NULL DEFAULT '1',
            external_sense_id TEXT NOT NULL DEFAULT '',
            external_synset_id TEXT NOT NULL DEFAULT '',
            source_slug TEXT NOT NULL DEFAULT '',
            source_locator TEXT NOT NULL DEFAULT '',
            confidence TEXT NOT NULL DEFAULT 'medium',
            review_status TEXT NOT NULL DEFAULT 'pending_review',
            notes TEXT NOT NULL DEFAULT '',
            priority INTEGER NOT NULL DEFAULT 50,
            review_reason TEXT NOT NULL DEFAULT '',
            UNIQUE(source_slug, source_locator)
        );

        CREATE TABLE IF NOT EXISTS review_relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_concept_slug TEXT NOT NULL,
            target_concept_slug TEXT NOT NULL,
            relationship_type TEXT NOT NULL,
            weight TEXT NOT NULL DEFAULT '0.5',
            source_slug TEXT NOT NULL DEFAULT '',
            source_locator TEXT NOT NULL DEFAULT '',
            confidence TEXT NOT NULL DEFAULT 'medium',
            review_status TEXT NOT NULL DEFAULT 'pending_review',
            notes TEXT NOT NULL DEFAULT '',
            priority INTEGER NOT NULL DEFAULT 50,
            review_reason TEXT NOT NULL DEFAULT '',
            UNIQUE(source_concept_slug, target_concept_slug, relationship_type)
        );

        CREATE TABLE IF NOT EXISTS review_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_concept_slug TEXT NOT NULL,
            target_concept_slug TEXT NOT NULL,
            mapping_type TEXT NOT NULL,
            weight TEXT NOT NULL DEFAULT '1.0',
            source_slug TEXT NOT NULL DEFAULT '',
            source_locator TEXT NOT NULL DEFAULT '',
            confidence TEXT NOT NULL DEFAULT 'medium',
            review_status TEXT NOT NULL DEFAULT 'pending_review',
            notes TEXT NOT NULL DEFAULT '',
            priority INTEGER NOT NULL DEFAULT 50,
            review_reason TEXT NOT NULL DEFAULT '',
            UNIQUE(source_concept_slug, target_concept_slug, mapping_type)
        );

        CREATE INDEX IF NOT EXISTS ix_review_concepts_status_priority
            ON review_concepts(review_status, priority DESC);

        CREATE INDEX IF NOT EXISTS ix_review_word_senses_status_priority
            ON review_word_senses(review_status, priority DESC);

        CREATE INDEX IF NOT EXISTS ix_review_relationships_status_priority
            ON review_relationships(review_status, priority DESC);

        CREATE INDEX IF NOT EXISTS ix_review_word_senses_concept
            ON review_word_senses(concept_slug);

        CREATE INDEX IF NOT EXISTS ix_review_relationships_source
            ON review_relationships(source_concept_slug);

        CREATE INDEX IF NOT EXISTS ix_review_relationships_target
            ON review_relationships(target_concept_slug);
        """
    )

    conn.commit()


def insert_rows(
    conn: sqlite3.Connection,
    *,
    table: str,
    columns: list[str],
    rows: list[dict[str, str]],
    classifier,
) -> int:
    inserted = 0

    all_columns = [
        *columns,
        "priority",
        "review_reason",
    ]

    placeholders = ", ".join(
        "?"
        for _ in all_columns
    )

    column_sql = ", ".join(all_columns)

    update_sql = ", ".join(
        f"{column} = excluded.{column}"
        for column in all_columns
        if column not in {"priority", "review_reason"}
    )

    sql = f"""
        INSERT INTO {table} ({column_sql})
        VALUES ({placeholders})
        ON CONFLICT DO UPDATE SET
            {update_sql},
            priority = excluded.priority,
            review_reason = excluded.review_reason
    """

    for row in rows:
        status, priority, reason = classifier(row)
        normalized = {
            column: row.get(column, "").strip()
            for column in columns
        }
        normalized["review_status"] = status
        normalized["priority"] = str(priority)
        normalized["review_reason"] = reason

        conn.execute(
            sql,
            [
                normalized.get(column, "")
                for column in all_columns
            ],
        )
        inserted += 1

    conn.commit()

    return inserted


def load_candidates(
    *,
    candidate_dir: Path,
    db_path: Path,
    replace: bool,
) -> dict[str, int]:
    if replace and db_path.exists():
        db_path.unlink()

    conn = connect(db_path)
    create_schema(conn)

    counts = {
        "concepts": insert_rows(
            conn,
            table="review_concepts",
            columns=CONCEPT_COLUMNS,
            rows=read_csv(candidate_dir / "candidate_concepts.csv"),
            classifier=preclassify_concept,
        ),
        "words": insert_rows(
            conn,
            table="review_words",
            columns=WORD_COLUMNS,
            rows=read_csv(candidate_dir / "candidate_words.csv"),
            classifier=preclassify_word,
        ),
        "word_senses": insert_rows(
            conn,
            table="review_word_senses",
            columns=WORD_SENSE_COLUMNS,
            rows=read_csv(candidate_dir / "candidate_word_senses.csv"),
            classifier=preclassify_word_sense,
        ),
        "relationships": insert_rows(
            conn,
            table="review_relationships",
            columns=RELATIONSHIP_COLUMNS,
            rows=read_csv(
                candidate_dir / "candidate_concept_relationships.csv"
            ),
            classifier=preclassify_relationship,
        ),
        "mappings": insert_rows(
            conn,
            table="review_mappings",
            columns=MAPPING_COLUMNS,
            rows=read_csv(
                candidate_dir / "candidate_concept_mappings.csv"
            ),
            classifier=lambda row: (
                normalize_status(row.get("review_status")),
                20,
                "optional_mapping",
            ),
        ),
    }

    conn.close()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load yellow-card candidate CSVs into SQLite review DB."
    )
    parser.add_argument(
        "--candidate-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/review/oewn-2025.sqlite"),
    )
    parser.add_argument(
        "--replace",
        action="store_true",
    )

    args = parser.parse_args()

    counts = load_candidates(
        candidate_dir=args.candidate_dir,
        db_path=args.db,
        replace=args.replace,
    )

    print(f"Loaded candidates into {args.db}")

    for name, count in counts.items():
        print(f"{name}: {count}")


if __name__ == "__main__":
    main()