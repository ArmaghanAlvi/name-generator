from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

from app.utils.text import normalize_text


CONCEPT_COLUMNS = [
    "slug",
    "label",
    "description",
    "domain",
    "status",
    "concept_type",
    "is_public",
    "external_source_slug",
    "external_concept_id",
]

CONCEPT_RELATIONSHIP_COLUMNS = [
    "source_concept_slug",
    "target_concept_slug",
    "relationship_type",
    "weight",
    "source_slug",
    "source_locator",
    "confidence",
    "review_status",
]

CONCEPT_MAPPING_COLUMNS = [
    "source_concept_slug",
    "target_concept_slug",
    "mapping_type",
    "weight",
    "source_slug",
    "source_locator",
    "confidence",
    "review_status",
]

WORD_COLUMNS = [
    "language_code",
    "text",
    "transliteration",
    "part_of_speech",
    "external_entry_id",
    "notes",
    "source_slug",
]

WORD_SENSE_COLUMNS = [
    "language_code",
    "word_text",
    "part_of_speech",
    "concept_slug",
    "gloss",
    "is_primary",
    "equivalence_type",
    "sense_rank",
    "external_sense_id",
    "external_synset_id",
    "source_slug",
    "source_locator",
    "confidence",
    "review_status",
]


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


def write_csv(
    path: Path,
    columns: list[str],
    rows: list[dict[str, str]],
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
                    column: row.get(column, "")
                    for column in columns
                }
            )


def copy_base_catalog(
    base_path: Path,
    output_path: Path,
    *,
    replace: bool,
) -> None:
    if output_path.exists():
        if not replace:
            raise FileExistsError(
                f"{output_path} already exists. "
                "Use --replace to overwrite it."
            )

        shutil.rmtree(output_path)

    shutil.copytree(
        base_path,
        output_path,
    )


def is_reviewed(row: dict[str, str]) -> bool:
    return row.get("review_status", "").strip().casefold() == "reviewed"


def reviewed_concept_is_accepted(
    row: dict[str, str],
) -> bool:
    """
    Candidate concepts may include workflow fields such as:
    decision, target_concept_slug, notes.

    This exporter only exports concepts that are reviewed and accepted
    as standalone searchable concepts.
    """
    if not is_reviewed(row):
        return False

    decision = row.get("decision", "").strip().casefold()

    return decision in {
        "",
        "accept",
        "accepted",
        "accept_new_concept",
        "new_concept",
        "standalone",
    }


def normalize_bool_string(value: str) -> str:
    normalized = value.strip().casefold()

    if normalized in {"true", "1", "yes", "y"}:
        return "true"

    if normalized in {"false", "0", "no", "n"}:
        return "false"

    return value.strip() or "true"


def normalize_part_of_speech(value: str) -> str:
    normalized = value.strip().casefold()

    return {
        "n": "noun",
        "v": "verb",
        "a": "adjective",
        "s": "adjective",
        "r": "adverb",
    }.get(normalized, normalized or "unknown")


def concept_key(row: dict[str, str]) -> str:
    return row["slug"].strip()


def relationship_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        row["source_concept_slug"].strip(),
        row["target_concept_slug"].strip(),
        row["relationship_type"].strip(),
    )


def mapping_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        row["source_concept_slug"].strip(),
        row["target_concept_slug"].strip(),
        row["mapping_type"].strip(),
    )


def word_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        row["language_code"].strip().casefold(),
        normalize_text(row["text"]),
        normalize_part_of_speech(row.get("part_of_speech", "")),
    )


def word_sense_key(row: dict[str, str]) -> tuple[str, str]:
    """
    Prefer source_slug + source_locator because the new database
    uniqueness rule is source_id + source_locator.
    """
    return (
        row["source_slug"].strip(),
        row["source_locator"].strip(),
    )


def candidate_word_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        row["language_code"].strip().casefold(),
        normalize_text(row["word_text"]),
        normalize_part_of_speech(row.get("part_of_speech", "")),
    )


def build_candidate_word_lookup(
    candidate_words: list[dict[str, str]],
) -> dict[tuple[str, str, str], dict[str, str]]:
    lookup: dict[tuple[str, str, str], dict[str, str]] = {}

    for row in candidate_words:
        key = word_key(row)
        lookup[key] = row

    return lookup


def export_concepts(
    *,
    output_path: Path,
    candidate_concepts: list[dict[str, str]],
) -> int:
    path = output_path / "concepts.csv"

    existing = read_csv(path)
    keys = {
        concept_key(row)
        for row in existing
    }

    added = 0

    for row in candidate_concepts:
        if not reviewed_concept_is_accepted(row):
            continue

        exported = {
            "slug": row["slug"].strip(),
            "label": row["label"].strip(),
            "description": row.get("description", "").strip(),
            "domain": row.get("domain", "").strip(),
            "status": row.get("status", "active").strip() or "active",
            "concept_type": row.get(
                "concept_type",
                "external_synset",
            ).strip()
            or "external_synset",
            "is_public": normalize_bool_string(
                row.get("is_public", "true")
            ),
            "external_source_slug": row.get(
                "external_source_slug",
                "",
            ).strip(),
            "external_concept_id": row.get(
                "external_concept_id",
                "",
            ).strip(),
        }

        key = concept_key(exported)

        if key in keys:
            continue

        existing.append(exported)
        keys.add(key)
        added += 1

    write_csv(
        path,
        CONCEPT_COLUMNS,
        existing,
    )

    return added


def export_relationships(
    *,
    output_path: Path,
    candidate_relationships: list[dict[str, str]],
) -> int:
    path = output_path / "concept_relationships.csv"

    existing = read_csv(path)
    keys = {
        relationship_key(row)
        for row in existing
    }

    added = 0

    for row in candidate_relationships:
        if not is_reviewed(row):
            continue

        exported = {
            "source_concept_slug": row["source_concept_slug"].strip(),
            "target_concept_slug": row["target_concept_slug"].strip(),
            "relationship_type": row["relationship_type"].strip(),
            "weight": row.get("weight", "0.5").strip() or "0.5",
            "source_slug": row["source_slug"].strip(),
            "source_locator": row["source_locator"].strip(),
            "confidence": row.get("confidence", "medium").strip()
            or "medium",
            "review_status": "reviewed",
        }

        key = relationship_key(exported)

        if key in keys:
            continue

        existing.append(exported)
        keys.add(key)
        added += 1

    write_csv(
        path,
        CONCEPT_RELATIONSHIP_COLUMNS,
        existing,
    )

    return added


def export_mappings(
    *,
    output_path: Path,
    candidate_mappings: list[dict[str, str]],
) -> int:
    path = output_path / "concept_mappings.csv"

    existing = read_csv(path)
    keys = {
        mapping_key(row)
        for row in existing
    }

    added = 0

    for row in candidate_mappings:
        if not is_reviewed(row):
            continue

        exported = {
            "source_concept_slug": row["source_concept_slug"].strip(),
            "target_concept_slug": row["target_concept_slug"].strip(),
            "mapping_type": row["mapping_type"].strip(),
            "weight": row.get("weight", "1.0").strip() or "1.0",
            "source_slug": row["source_slug"].strip(),
            "source_locator": row["source_locator"].strip(),
            "confidence": row.get("confidence", "medium").strip()
            or "medium",
            "review_status": "reviewed",
        }

        key = mapping_key(exported)

        if key in keys:
            continue

        existing.append(exported)
        keys.add(key)
        added += 1

    write_csv(
        path,
        CONCEPT_MAPPING_COLUMNS,
        existing,
    )

    return added


def export_words(
    *,
    output_path: Path,
    candidate_words: list[dict[str, str]],
    candidate_word_senses: list[dict[str, str]],
) -> int:
    """
    Export reviewed candidate words.

    Also exports a candidate word if a reviewed word sense refers to it.
    This prevents a reviewed sense from failing import because the matching
    word row was still pending_review.
    """
    path = output_path / "words.csv"

    existing = read_csv(path)
    keys = {
        word_key(row)
        for row in existing
    }

    candidate_lookup = build_candidate_word_lookup(
        candidate_words
    )

    rows_to_consider: list[dict[str, str]] = []

    for row in candidate_words:
        if is_reviewed(row):
            rows_to_consider.append(row)

    for sense in candidate_word_senses:
        if not is_reviewed(sense):
            continue

        key = candidate_word_key(sense)
        candidate_word = candidate_lookup.get(key)

        if candidate_word is not None:
            rows_to_consider.append(candidate_word)

    added = 0

    for row in rows_to_consider:
        exported = {
            "language_code": row["language_code"].strip().casefold(),
            "text": row["text"].strip(),
            "transliteration": row.get("transliteration", "").strip(),
            "part_of_speech": normalize_part_of_speech(
                row.get("part_of_speech", "")
            ),
            "external_entry_id": row.get(
                "external_entry_id",
                "",
            ).strip(),
            "notes": row.get("notes", "").strip(),
            "source_slug": row["source_slug"].strip(),
        }

        key = word_key(exported)

        if key in keys:
            continue

        existing.append(exported)
        keys.add(key)
        added += 1

    write_csv(
        path,
        WORD_COLUMNS,
        existing,
    )

    return added


def export_word_senses(
    *,
    output_path: Path,
    candidate_word_senses: list[dict[str, str]],
) -> int:
    path = output_path / "word_senses.csv"

    existing = read_csv(path)
    keys = {
        word_sense_key(row)
        for row in existing
        if row.get("source_slug", "").strip()
        and row.get("source_locator", "").strip()
    }

    added = 0

    for row in candidate_word_senses:
        if not is_reviewed(row):
            continue

        exported = {
            "language_code": row["language_code"].strip().casefold(),
            "word_text": row["word_text"].strip(),
            "part_of_speech": normalize_part_of_speech(
                row.get("part_of_speech", "")
            ),
            "concept_slug": row["concept_slug"].strip(),
            "gloss": row["gloss"].strip(),
            "is_primary": normalize_bool_string(
                row.get("is_primary", "true")
            ),
            "equivalence_type": row.get(
                "equivalence_type",
                "canonical",
            ).strip()
            or "canonical",
            "sense_rank": row.get("sense_rank", "1").strip() or "1",
            "external_sense_id": row.get(
                "external_sense_id",
                "",
            ).strip(),
            "external_synset_id": row.get(
                "external_synset_id",
                "",
            ).strip(),
            "source_slug": row["source_slug"].strip(),
            "source_locator": row["source_locator"].strip(),
            "confidence": row.get("confidence", "medium").strip()
            or "medium",
            "review_status": "reviewed",
        }

        key = word_sense_key(exported)

        if key in keys:
            continue

        existing.append(exported)
        keys.add(key)
        added += 1

    write_csv(
        path,
        WORD_SENSE_COLUMNS,
        existing,
    )

    return added


def export_reviewed_oewn_yellow(
    *,
    base_path: Path,
    candidates_path: Path,
    output_path: Path,
    replace: bool,
) -> dict[str, int]:
    copy_base_catalog(
        base_path,
        output_path,
        replace=replace,
    )

    candidate_concepts = read_csv(
        candidates_path / "candidate_concepts.csv"
    )
    candidate_mappings = read_csv(
        candidates_path / "candidate_concept_mappings.csv"
    )
    candidate_relationships = read_csv(
        candidates_path / "candidate_concept_relationships.csv"
    )
    candidate_words = read_csv(
        candidates_path / "candidate_words.csv"
    )
    candidate_word_senses = read_csv(
        candidates_path / "candidate_word_senses.csv"
    )

    added = {
        "concepts": export_concepts(
            output_path=output_path,
            candidate_concepts=candidate_concepts,
        ),
        "concept_relationships": export_relationships(
            output_path=output_path,
            candidate_relationships=candidate_relationships,
        ),
        "concept_mappings": export_mappings(
            output_path=output_path,
            candidate_mappings=candidate_mappings,
        ),
        "words": export_words(
            output_path=output_path,
            candidate_words=candidate_words,
            candidate_word_senses=candidate_word_senses,
        ),
        "word_senses": export_word_senses(
            output_path=output_path,
            candidate_word_senses=candidate_word_senses,
        ),
    }

    return added


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export reviewed OEWN yellow-card candidates into "
            "the current curated catalog schema."
        )
    )

    parser.add_argument(
        "--base",
        type=Path,
        required=True,
        help="Existing curated catalog directory, e.g. data/curated/v3.",
    )

    parser.add_argument(
        "--candidates",
        type=Path,
        required=True,
        help=(
            "Directory containing candidate_concepts.csv, "
            "candidate_words.csv, candidate_word_senses.csv, "
            "candidate_concept_relationships.csv, and optionally "
            "candidate_concept_mappings.csv."
        ),
    )

    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output curated catalog directory, e.g. data/curated/v4.",
    )

    parser.add_argument(
        "--replace",
        action="store_true",
    )

    args = parser.parse_args()

    added = export_reviewed_oewn_yellow(
        base_path=args.base,
        candidates_path=args.candidates,
        output_path=args.out,
        replace=args.replace,
    )

    print(f"Exported reviewed OEWN yellow rows to {args.out}")

    for table, count in added.items():
        print(f"Added {table}: {count}")


if __name__ == "__main__":
    main()