from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

from app.utils.text import normalize_text


WORD_SENSE_COLUMNS = [
    "source_slug",
    "language_code",
    "word_text",
    "part_of_speech",
    "concept_slug",
    "gloss",
    "match_method",
    "match_confidence",
    "source_locator",
    "review_status",
    "notes",
]

CANDIDATE_CONCEPT_COLUMNS = [
    "candidate_slug",
    "label",
    "description",
    "domain",
    "source_slug",
    "source_locator",
    "proposed_from_word",
    "match_confidence",
    "review_status",
    "decision",
    "merge_into_concept_slug",
    "notes",
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
        )

        writer.writeheader()
        writer.writerows(rows)


def load_alias_map(
    aliases_path: Path,
) -> dict[str, set[str]]:
    alias_map: dict[str, set[str]] = defaultdict(set)

    for row in read_csv(aliases_path):
        alias_map[normalize_text(row["text"])].add(
            row["concept_slug"].strip()
        )

    return alias_map


def load_concept_slugs(
    concepts_path: Path,
) -> set[str]:
    return {
        row["slug"].strip()
        for row in read_csv(concepts_path)
        if row.get("slug", "").strip()
    }


def contains_phrase(
    text: str,
    phrase: str,
) -> bool:
    pattern = r"\b" + re.escape(phrase) + r"\b"
    return (
        re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )
        is not None
    )


def candidate_slug_from_synset(
    synset_id: str,
) -> str:
    cleaned = (
        synset_id.replace("ewn-", "")
        .replace("-", "_")
        .replace(".", "_")
    )

    return f"oewn_{cleaned}"


def make_label(
    lemma: str,
) -> str:
    return lemma.replace("_", " ").title()


def match_raw_entries(
    raw_entries_path: Path,
    concepts_path: Path,
    aliases_path: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    aliases = load_alias_map(aliases_path)
    concept_slugs = load_concept_slugs(concepts_path)

    candidate_word_senses: list[dict[str, str]] = []
    candidate_concepts: list[dict[str, str]] = []
    seen_concepts: set[str] = set()

    for row in read_csv(raw_entries_path):
        lemma = row["lemma"].strip()
        normalized_lemma = normalize_text(lemma)
        definition = row.get("definition", "").strip()
        normalized_definition = normalize_text(definition)
        synonyms = [
            value.strip()
            for value in row.get("synonyms", "").split("|")
            if value.strip()
        ]

        matches: list[tuple[str, str, float]] = []

        if normalized_lemma in aliases:
            for concept_slug in sorted(aliases[normalized_lemma]):
                matches.append(
                    (
                        concept_slug,
                        "lemma_alias",
                        0.98,
                    )
                )

        for synonym in synonyms:
            normalized_synonym = normalize_text(synonym)

            if normalized_synonym in aliases:
                for concept_slug in sorted(aliases[normalized_synonym]):
                    matches.append(
                        (
                            concept_slug,
                            "synonym_alias",
                            0.90,
                        )
                    )

        for alias, alias_concepts in aliases.items():
            if len(alias) < 4:
                continue

            if contains_phrase(
                normalized_definition,
                alias,
            ):
                for concept_slug in sorted(alias_concepts):
                    matches.append(
                        (
                            concept_slug,
                            "definition_alias",
                            0.72,
                        )
                    )

        # Remove duplicate concept matches while keeping best confidence.
        best_by_concept: dict[str, tuple[str, float]] = {}

        for concept_slug, method, confidence in matches:
            if concept_slug not in concept_slugs:
                continue

            existing = best_by_concept.get(concept_slug)

            if existing is None or confidence > existing[1]:
                best_by_concept[concept_slug] = (
                    method,
                    confidence,
                )

        if best_by_concept:
            for concept_slug, (
                method,
                confidence,
            ) in sorted(best_by_concept.items()):
                candidate_word_senses.append(
                    {
                        "source_slug": row["source_slug"],
                        "language_code": row["language_code"],
                        "word_text": lemma,
                        "part_of_speech": row["part_of_speech"],
                        "concept_slug": concept_slug,
                        "gloss": definition,
                        "match_method": method,
                        "match_confidence": f"{confidence:.2f}",
                        "source_locator": row["source_locator"],
                        "review_status": "pending_review",
                        "notes": "",
                    }
                )
        else:
            candidate_slug = candidate_slug_from_synset(
                row["synset_id"]
            )

            if candidate_slug in seen_concepts:
                continue

            seen_concepts.add(candidate_slug)

            candidate_concepts.append(
                {
                    "candidate_slug": candidate_slug,
                    "label": make_label(lemma),
                    "description": definition,
                    "domain": "",
                    "source_slug": row["source_slug"],
                    "source_locator": row["source_locator"],
                    "proposed_from_word": lemma,
                    "match_confidence": "0.40",
                    "review_status": "pending_review",
                    "decision": "",
                    "merge_into_concept_slug": "",
                    "notes": (
                        "No confident match to existing concept aliases."
                    ),
                }
            )

    return candidate_word_senses, candidate_concepts


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Match extracted raw entries to existing concepts."
        )
    )

    parser.add_argument(
        "--raw",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--concepts",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--aliases",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--out-dir",
        type=Path,
        required=True,
    )

    args = parser.parse_args()

    senses, concepts = match_raw_entries(
        args.raw,
        args.concepts,
        args.aliases,
    )

    write_csv(
        args.out_dir / "candidate_word_senses.csv",
        WORD_SENSE_COLUMNS,
        senses,
    )

    write_csv(
        args.out_dir / "candidate_concepts.csv",
        CANDIDATE_CONCEPT_COLUMNS,
        concepts,
    )

    print(
        f"Wrote {len(senses)} candidate word senses."
    )
    print(
        f"Wrote {len(concepts)} candidate concepts."
    )


if __name__ == "__main__":
    main()