from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

from app.utils.text import normalize_text


WORDS_COLUMNS = [
    "language_code",
    "text",
    "transliteration",
    "part_of_speech",
    "notes",
    "source_slug",
]

WORD_SENSES_COLUMNS = [
    "language_code",
    "word_text",
    "concept_slug",
    "gloss",
    "is_primary",
    "source_slug",
    "source_locator",
    "confidence",
    "review_status",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def write_csv(
    path: Path,
    columns: list[str],
    rows: list[dict[str, str]],
) -> None:
    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=columns,
        )

        writer.writeheader()
        writer.writerows(rows)


def normalize_part_of_speech(value: str) -> str:
    normalized = value.strip().casefold()

    return {
        "n": "noun",
        "v": "verb",
        "a": "adjective",
        "s": "adjective",
        "r": "adverb",
    }.get(normalized, normalized or "unknown")


def confidence_label(value: str) -> str:
    try:
        score = float(value)
    except ValueError:
        return "medium"

    if score >= 0.90:
        return "high"

    if score >= 0.70:
        return "medium"

    return "low"


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


def export_reviewed(
    *,
    base_path: Path,
    candidates_path: Path,
    output_path: Path,
    replace: bool,
) -> None:
    copy_base_catalog(
        base_path,
        output_path,
        replace=replace,
    )

    words_path = output_path / "words.csv"
    word_senses_path = output_path / "word_senses.csv"

    existing_words = read_csv(words_path)
    existing_senses = read_csv(word_senses_path)

    word_keys = {
        (
            row["language_code"].strip().casefold(),
            normalize_text(row["text"]),
        )
        for row in existing_words
    }

    sense_keys = {
        (
            row["language_code"].strip().casefold(),
            normalize_text(row["word_text"]),
            row["concept_slug"].strip(),
        )
        for row in existing_senses
    }

    candidates = read_csv(candidates_path)

    added_words = 0
    added_senses = 0

    for row in candidates:
        if row["review_status"].strip().casefold() != "reviewed":
            continue

        language_code = row["language_code"].strip().casefold()
        word_text = row["word_text"].strip()
        concept_slug = row["concept_slug"].strip()
        source_slug = row["source_slug"].strip()

        word_key = (
            language_code,
            normalize_text(word_text),
        )

        if word_key not in word_keys:
            existing_words.append(
                {
                    "language_code": language_code,
                    "text": word_text,
                    "transliteration": "",
                    "part_of_speech": normalize_part_of_speech(
                        row["part_of_speech"]
                    ),
                    "notes": (
                        "Imported from Open English Wordnet."
                    ),
                    "source_slug": source_slug,
                }
            )

            word_keys.add(word_key)
            added_words += 1

        sense_key = (
            language_code,
            normalize_text(word_text),
            concept_slug,
        )

        if sense_key not in sense_keys:
            existing_senses.append(
                {
                    "language_code": language_code,
                    "word_text": word_text,
                    "concept_slug": concept_slug,
                    "gloss": row["gloss"].strip(),
                    "is_primary": "true",
                    "source_slug": source_slug,
                    "source_locator": row["source_locator"].strip(),
                    "confidence": confidence_label(
                        row["match_confidence"]
                    ),
                    "review_status": "reviewed",
                }
            )

            sense_keys.add(sense_key)
            added_senses += 1

    write_csv(
        words_path,
        WORDS_COLUMNS,
        existing_words,
    )

    write_csv(
        word_senses_path,
        WORD_SENSES_COLUMNS,
        existing_senses,
    )

    print(
        f"Exported reviewed yellow-card rows to {output_path}"
    )
    print(
        f"Added words: {added_words}"
    )
    print(
        f"Added word senses: {added_senses}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export reviewed candidate word senses into "
            "the curated catalog CSV format."
        )
    )

    parser.add_argument(
        "--base",
        type=Path,
        required=True,
        help="Existing curated catalog directory, e.g. data/curated/v1.",
    )

    parser.add_argument(
        "--candidates",
        type=Path,
        required=True,
        help="candidate_word_senses.csv file.",
    )

    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output curated catalog directory, e.g. data/curated/v2.",
    )

    parser.add_argument(
        "--replace",
        action="store_true",
    )

    args = parser.parse_args()

    export_reviewed(
        base_path=args.base,
        candidates_path=args.candidates,
        output_path=args.out,
        replace=args.replace,
    )


if __name__ == "__main__":
    main()