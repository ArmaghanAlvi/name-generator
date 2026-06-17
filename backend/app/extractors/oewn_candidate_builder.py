from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.utils.text import normalize_text


CANDIDATE_CONCEPT_COLUMNS = [
    "slug",
    "label",
    "description",
    "domain",
    "status",
    "concept_type",
    "is_public",
    "external_source_slug",
    "external_concept_id",
    "review_status",
    "decision",
    "target_concept_slug",
    "notes",
]

CANDIDATE_MAPPING_COLUMNS = [
    "source_concept_slug",
    "target_concept_slug",
    "mapping_type",
    "weight",
    "source_slug",
    "source_locator",
    "confidence",
    "review_status",
]

CANDIDATE_WORD_COLUMNS = [
    "language_code",
    "text",
    "transliteration",
    "part_of_speech",
    "external_entry_id",
    "notes",
    "source_slug",
    "review_status",
]

CANDIDATE_WORD_SENSE_COLUMNS = [
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

CANDIDATE_RELATIONSHIP_COLUMNS = [
    "source_concept_slug",
    "target_concept_slug",
    "relationship_type",
    "weight",
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
) -> dict[str, str]:
    aliases: dict[str, str] = {}

    for row in read_csv(aliases_path):
        aliases[
            normalize_text(row["text"])
        ] = row["concept_slug"].strip()

    return aliases


def normalize_pos(value: str) -> str:
    normalized = value.strip().casefold()

    return {
        "n": "noun",
        "v": "verb",
        "a": "adjective",
        "s": "adjective",
        "r": "adverb",
    }.get(normalized, normalized or "unknown")


def relationship_weight(
    rel_type: str,
) -> tuple[str, str]:
    normalized = rel_type.strip().casefold()

    # These are intentionally conservative.
    # You can tune them after seeing OEWN output.
    mapping = {
        "similar": ("near_synonym", "0.90"),
        "also": ("associated", "0.75"),
        "hypernym": ("broader", "0.65"),
        "hyponym": ("narrower", "0.65"),
        "domain_topic": ("associated", "0.55"),
        "has_domain_topic": ("associated", "0.55"),
        "mero_part": ("associated", "0.45"),
        "holo_part": ("associated", "0.45"),
    }

    return mapping.get(
        normalized,
        ("associated", "0.40"),
    )


def build_candidates(
    *,
    raw_entries_path: Path,
    raw_synsets_path: Path,
    raw_relations_path: Path,
    concepts_path: Path,
    aliases_path: Path,
    out_dir: Path,
) -> None:
    aliases = load_alias_map(aliases_path)

    raw_entries = read_csv(raw_entries_path)
    raw_synsets = read_csv(raw_synsets_path)
    raw_relations = read_csv(raw_relations_path)

    synset_slug_by_id = {
        row["synset_id"]: row["candidate_concept_slug"]
        for row in raw_synsets
    }

    candidate_concepts: list[dict[str, str]] = []
    candidate_mappings: list[dict[str, str]] = []
    candidate_words: list[dict[str, str]] = []
    candidate_word_senses: list[dict[str, str]] = []
    candidate_relationships: list[dict[str, str]] = []

    seen_words: set[tuple[str, str, str]] = set()

    for synset in raw_synsets:
        source_slug = synset["source_slug"]
        synset_id = synset["synset_id"]
        concept_slug = synset["candidate_concept_slug"]
        synonyms = [
            value.strip()
            for value in synset.get("synonyms", "").split("|")
            if value.strip()
        ]

        candidate_concepts.append(
            {
                "slug": concept_slug,
                "label": synset["label"],
                "description": synset["definition"],
                "domain": "",
                "status": "active",
                "concept_type": "external_synset",
                "is_public": "true",
                "external_source_slug": source_slug,
                "external_concept_id": synset_id,
                "review_status": "pending_review",
                "decision": "",
                "target_concept_slug": "",
                "notes": "OEWN external synset candidate.",
            }
        )

        # Try to map this OEWN synset to an existing public app concept
        # by checking its synonyms against current concept aliases.
        for synonym in synonyms:
            mapped_concept = aliases.get(
                normalize_text(synonym)
            )

            if mapped_concept is None:
                continue

            candidate_mappings.append(
                {
                    "source_concept_slug": concept_slug,
                    "target_concept_slug": mapped_concept,
                    "mapping_type": "exact",
                    "weight": "1.0",
                    "source_slug": source_slug,
                    "source_locator": synset_id,
                    "confidence": "medium",
                    "review_status": "pending_review",
                }
            )

            break

    for entry in raw_entries:
        language_code = entry["language_code"].strip().casefold()
        word_text = entry["lemma"].strip()
        part_of_speech = normalize_pos(entry["part_of_speech"])
        source_slug = entry["source_slug"]
        synset_id = entry["synset_id"]
        concept_slug = synset_slug_by_id.get(synset_id)

        if concept_slug is None:
            continue

        word_key = (
            language_code,
            normalize_text(word_text),
            part_of_speech,
        )

        if word_key not in seen_words:
            seen_words.add(word_key)

            candidate_words.append(
                {
                    "language_code": language_code,
                    "text": word_text,
                    "transliteration": "",
                    "part_of_speech": part_of_speech,
                    "external_entry_id": entry["lexical_entry_id"],
                    "notes": "Imported from Open English Wordnet.",
                    "source_slug": source_slug,
                    "review_status": "pending_review",
                }
            )

        # Default all senses to near_equivalent until reviewed.
        # During review, mark the desired headword as canonical/direct.
        candidate_word_senses.append(
            {
                "language_code": language_code,
                "word_text": word_text,
                "part_of_speech": part_of_speech,
                "concept_slug": concept_slug,
                "gloss": entry["definition"],
                "is_primary": "true",
                "equivalence_type": "canonical",
                "sense_rank": "1",
                "external_sense_id": entry["sense_id"],
                "external_synset_id": synset_id,
                "source_slug": source_slug,
                "source_locator": entry["source_locator"],
                "confidence": "medium",
                "review_status": "pending_review",
            }
        )

    for relation in raw_relations:
        source_slug = relation["source_slug"]
        source_concept_slug = synset_slug_by_id.get(
            relation["source_synset_id"]
        )
        target_concept_slug = synset_slug_by_id.get(
            relation["target_synset_id"]
        )

        if source_concept_slug is None or target_concept_slug is None:
            continue

        relationship_type, weight = relationship_weight(
            relation["relationship_type"]
        )

        candidate_relationships.append(
            {
                "source_concept_slug": source_concept_slug,
                "target_concept_slug": target_concept_slug,
                "relationship_type": relationship_type,
                "weight": weight,
                "source_slug": source_slug,
                "source_locator": relation["source_locator"],
                "confidence": "medium",
                "review_status": "pending_review",
            }
        )

    write_csv(
        out_dir / "candidate_concepts.csv",
        CANDIDATE_CONCEPT_COLUMNS,
        candidate_concepts,
    )
    write_csv(
        out_dir / "candidate_concept_mappings.csv",
        CANDIDATE_MAPPING_COLUMNS,
        candidate_mappings,
    )
    write_csv(
        out_dir / "candidate_words.csv",
        CANDIDATE_WORD_COLUMNS,
        candidate_words,
    )
    write_csv(
        out_dir / "candidate_word_senses.csv",
        CANDIDATE_WORD_SENSE_COLUMNS,
        candidate_word_senses,
    )
    write_csv(
        out_dir / "candidate_concept_relationships.csv",
        CANDIDATE_RELATIONSHIP_COLUMNS,
        candidate_relationships,
    )

    print(f"Wrote {len(candidate_concepts)} candidate concepts.")
    print(f"Wrote {len(candidate_mappings)} candidate mappings.")
    print(f"Wrote {len(candidate_words)} candidate words.")
    print(f"Wrote {len(candidate_word_senses)} candidate word senses.")
    print(f"Wrote {len(candidate_relationships)} candidate relationships.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build OEWN candidate import files."
    )

    parser.add_argument("--raw-entries", type=Path, required=True)
    parser.add_argument("--raw-synsets", type=Path, required=True)
    parser.add_argument("--raw-relations", type=Path, required=True)
    parser.add_argument("--concepts", type=Path, required=True)
    parser.add_argument("--aliases", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)

    args = parser.parse_args()

    build_candidates(
        raw_entries_path=args.raw_entries,
        raw_synsets_path=args.raw_synsets,
        raw_relations_path=args.raw_relations,
        concepts_path=args.concepts,
        aliases_path=args.aliases,
        out_dir=args.out_dir,
    )


if __name__ == "__main__":
    main()