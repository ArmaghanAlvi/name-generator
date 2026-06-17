from __future__ import annotations

import argparse
import csv
import shutil
import sqlite3
from pathlib import Path

from app.extractors.export_reviewed_oewn_yellow import (
    export_reviewed_oewn_yellow,
)
from app.review.constants import (
    CONCEPT_COLUMNS,
    MAPPING_COLUMNS,
    RELATIONSHIP_COLUMNS,
    WORD_COLUMNS,
    WORD_SENSE_COLUMNS,
)


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def write_csv(
    path: Path,
    columns: list[str],
    rows: list[sqlite3.Row],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=columns,
            extrasaction="ignore",
        )

        writer.writeheader()

        for row in rows:
            writer.writerow(
                {
                    column: row[column]
                    if column in row.keys()
                    else ""
                    for column in columns
                }
            )


def fetch_reviewed(
    conn: sqlite3.Connection,
    table: str,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            f"""
            SELECT *
            FROM {table}
            WHERE review_status = 'reviewed'
            ORDER BY id
            """
        )
    )


def export_review_db_to_candidate_csvs(
    *,
    db_path: Path,
    candidates_out: Path,
    replace: bool,
) -> dict[str, int]:
    if candidates_out.exists():
        if not replace:
            raise FileExistsError(
                f"{candidates_out} already exists. Use --replace."
            )

        shutil.rmtree(candidates_out)

    candidates_out.mkdir(
        parents=True,
        exist_ok=True,
    )

    conn = connect(db_path)

    tables = {
        "candidate_concepts.csv": (
            "review_concepts",
            CONCEPT_COLUMNS,
        ),
        "candidate_words.csv": (
            "review_words",
            WORD_COLUMNS,
        ),
        "candidate_word_senses.csv": (
            "review_word_senses",
            WORD_SENSE_COLUMNS,
        ),
        "candidate_concept_relationships.csv": (
            "review_relationships",
            RELATIONSHIP_COLUMNS,
        ),
        "candidate_concept_mappings.csv": (
            "review_mappings",
            MAPPING_COLUMNS,
        ),
    }

    counts: dict[str, int] = {}

    for filename, (
        table,
        columns,
    ) in tables.items():
        rows = fetch_reviewed(
            conn,
            table,
        )

        write_csv(
            candidates_out / filename,
            columns,
            rows,
        )

        counts[filename] = len(rows)

    conn.close()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export reviewed SQLite rows into curated yellow-card CSVs."
        )
    )

    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/review/oewn-2025.sqlite"),
    )
    parser.add_argument(
        "--base",
        type=Path,
        required=True,
        help="Base curated directory, e.g. data/curated/v4.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output curated directory, e.g. data/curated/v5.",
    )
    parser.add_argument(
        "--candidate-out",
        type=Path,
        default=Path("data/review/exported-candidates/oewn-2025"),
    )
    parser.add_argument(
        "--replace",
        action="store_true",
    )

    args = parser.parse_args()

    counts = export_review_db_to_candidate_csvs(
        db_path=args.db,
        candidates_out=args.candidate_out,
        replace=args.replace,
    )

    print("Exported reviewed rows from SQLite:")

    for filename, count in counts.items():
        print(f"{filename}: {count}")

    added = export_reviewed_oewn_yellow(
        base_path=args.base,
        candidates_path=args.candidate_out,
        output_path=args.out,
        replace=args.replace,
    )

    print(f"\nCreated curated catalog: {args.out}")

    for table, count in added.items():
        print(f"Added {table}: {count}")


if __name__ == "__main__":
    main()