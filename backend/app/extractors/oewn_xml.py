from __future__ import annotations

import argparse
import csv
import gzip
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import TextIO

from app.utils.text import normalize_text


RAW_ENTRY_COLUMNS = [
    "source_slug",
    "language_code",
    "source_locator",
    "synset_id",
    "sense_id",
    "lemma",
    "normalized_lemma",
    "part_of_speech",
    "definition",
    "synonyms",
    "lexical_entry_id",
    "extraction_confidence",
    "review_status",
]

RAW_SYNSET_COLUMNS = [
    "source_slug",
    "language_code",
    "synset_id",
    "candidate_concept_slug",
    "label",
    "part_of_speech",
    "definition",
    "synonyms",
    "source_locator",
    "review_status",
]

RAW_SYNSET_RELATION_COLUMNS = [
    "source_slug",
    "source_synset_id",
    "target_synset_id",
    "relationship_type",
    "source_locator",
    "review_status",
]


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]

    return tag


def open_text(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")

    return path.open("r", encoding="utf-8")


def candidate_slug_from_synset_id(
    synset_id: str,
) -> str:
    cleaned = synset_id.strip()

    if cleaned.startswith("oewn-"):
        cleaned = cleaned.removeprefix("oewn-")
    elif cleaned.startswith("ewn-"):
        cleaned = cleaned.removeprefix("ewn-")

    cleaned = (
        cleaned
        .replace("-", "_")
        .replace(".", "_")
    )

    return f"oewn_{cleaned}"


def clean_lemma_for_label(value: str) -> str:
    return (
        value.replace("_", " ")
        .replace("-", " ")
        .strip()
    )


def concept_label_from_synonyms(
    synonyms: list[str],
    *,
    fallback_slug: str,
) -> str:
    cleaned_synonyms = []

    for synonym in synonyms:
        cleaned = clean_lemma_for_label(synonym)

        if not cleaned:
            continue

        if cleaned not in cleaned_synonyms:
            cleaned_synonyms.append(cleaned)

    if cleaned_synonyms:
        return " / ".join(cleaned_synonyms[:3]).title()

    return fallback_slug.replace("_", " ").title()


def clean_definition(value: str) -> str:
    return " ".join(
        value.strip().split()
    )


def child_by_name(
    element: ET.Element,
    name: str,
) -> ET.Element | None:
    for child in element:
        if local_name(child.tag) == name:
            return child

    return None


def children_by_name(
    element: ET.Element,
    name: str,
) -> list[ET.Element]:
    return [
        child
        for child in element
        if local_name(child.tag) == name
    ]


def element_text(
    element: ET.Element | None,
) -> str:
    if element is None:
        return ""

    return " ".join(
        part.strip()
        for part in element.itertext()
        if part.strip()
    )


def load_manifest(path: Path) -> dict:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def load_sample_terms(path: Path | None) -> set[str]:
    if path is None:
        return set()

    return {
        normalize_text(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def parse_oewn_xml(
    xml_path: Path,
    *,
    source_slug: str,
    language_code: str,
    sample_terms: set[str],
    max_rows: int | None,
) -> list[dict[str, str]]:
    with open_text(xml_path) as file:
        tree = ET.parse(file)

    root = tree.getroot()

    senses_by_synset: dict[str, list[dict[str, str]]] = defaultdict(list)
    definitions_by_synset: dict[str, str] = {}
    pos_by_synset: dict[str, str] = {}

    for element in root.iter():
        if local_name(element.tag) != "LexicalEntry":
            continue

        lexical_entry_id = element.attrib.get("id", "")

        lemma_element = child_by_name(element, "Lemma")

        if lemma_element is None:
            continue

        lemma = (
            lemma_element.attrib.get("writtenForm")
            or lemma_element.attrib.get("lemma")
            or ""
        ).replace("_", " ").strip()

        part_of_speech = (
            lemma_element.attrib.get("partOfSpeech")
            or ""
        ).strip()

        if not lemma:
            continue

        normalized = normalize_text(lemma)

        if sample_terms and normalized not in sample_terms:
            continue

        for sense in children_by_name(element, "Sense"):
            synset_id = sense.attrib.get("synset", "").strip()
            sense_id = sense.attrib.get("id", "").strip()

            if not synset_id or not sense_id:
                continue

            senses_by_synset[synset_id].append(
                {
                    "sense_id": sense_id,
                    "lemma": lemma,
                    "normalized_lemma": normalized,
                    "part_of_speech": part_of_speech,
                    "lexical_entry_id": lexical_entry_id,
                }
            )

    for element in root.iter():
        if local_name(element.tag) != "Synset":
            continue

        synset_id = element.attrib.get("id", "").strip()

        if not synset_id:
            continue

        definition = element_text(
            child_by_name(element, "Definition")
        )

        definitions_by_synset[synset_id] = definition
        pos_by_synset[synset_id] = element.attrib.get(
            "partOfSpeech",
            "",
        ).strip()

    rows: list[dict[str, str]] = []

    for synset_id, senses in senses_by_synset.items():
        synonyms = sorted(
            {
                sense["lemma"]
                for sense in senses
            }
        )

        for sense in senses:
            part_of_speech = (
                sense["part_of_speech"]
                or pos_by_synset.get(synset_id, "")
            )

            rows.append(
                {
                    "source_slug": source_slug,
                    "language_code": language_code,
                    "source_locator": (
                        f"{synset_id}#{sense['sense_id']}"
                    ),
                    "synset_id": synset_id,
                    "sense_id": sense["sense_id"],
                    "lemma": sense["lemma"],
                    "normalized_lemma": sense["normalized_lemma"],
                    "part_of_speech": part_of_speech,
                    "definition": definitions_by_synset.get(
                        synset_id,
                        "",
                    ),
                    "synonyms": "|".join(synonyms),
                    "lexical_entry_id": sense["lexical_entry_id"],
                    "extraction_confidence": "1.00",
                    "review_status": "extracted",
                }
            )

            if max_rows is not None and len(rows) >= max_rows:
                return rows

    return rows


def parse_oewn_xml_with_synsets(
    xml_path: Path,
    *,
    source_slug: str,
    language_code: str,
    sample_terms: set[str],
    max_rows: int | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    with open_text(xml_path) as file:
        tree = ET.parse(file)

    root = tree.getroot()

    senses_by_synset: dict[str, list[dict[str, str]]] = defaultdict(list)
    definitions_by_synset: dict[str, str] = {}
    pos_by_synset: dict[str, str] = {}
    relations_by_synset: dict[str, list[dict[str, str]]] = defaultdict(list)

    for element in root.iter():
        if local_name(element.tag) != "LexicalEntry":
            continue

        lexical_entry_id = element.attrib.get("id", "")
        lemma_element = child_by_name(element, "Lemma")

        if lemma_element is None:
            continue

        lemma = (
            lemma_element.attrib.get("writtenForm")
            or lemma_element.attrib.get("lemma")
            or ""
        ).replace("_", " ").strip()

        part_of_speech = (
            lemma_element.attrib.get("partOfSpeech")
            or ""
        ).strip()

        if not lemma:
            continue

        normalized = normalize_text(lemma)

        if sample_terms and normalized not in sample_terms:
            continue

        for sense in children_by_name(element, "Sense"):
            synset_id = sense.attrib.get("synset", "").strip()
            sense_id = sense.attrib.get("id", "").strip()

            if not synset_id or not sense_id:
                continue

            senses_by_synset[synset_id].append(
                {
                    "sense_id": sense_id,
                    "lemma": lemma,
                    "normalized_lemma": normalized,
                    "part_of_speech": part_of_speech,
                    "lexical_entry_id": lexical_entry_id,
                }
            )

    for element in root.iter():
        if local_name(element.tag) != "Synset":
            continue

        synset_id = element.attrib.get("id", "").strip()

        if not synset_id:
            continue

        definition = element_text(
            child_by_name(element, "Definition")
        )

        definitions_by_synset[synset_id] = definition
        pos_by_synset[synset_id] = element.attrib.get(
            "partOfSpeech",
            "",
        ).strip()

        for relation in children_by_name(element, "SynsetRelation"):
            target = relation.attrib.get("target", "").strip()
            rel_type = (
                relation.attrib.get("relType")
                or relation.attrib.get("rel")
                or ""
            ).strip()

            if not target or not rel_type:
                continue

            relations_by_synset[synset_id].append(
                {
                    "source_slug": source_slug,
                    "source_synset_id": synset_id,
                    "target_synset_id": target,
                    "relationship_type": rel_type,
                    "source_locator": f"{synset_id}->{target}:{rel_type}",
                    "review_status": "extracted",
                }
            )

    raw_entries: list[dict[str, str]] = []
    raw_synsets: list[dict[str, str]] = []
    raw_relations: list[dict[str, str]] = []

    for synset_id, senses in senses_by_synset.items():
        synonyms = sorted(
            {
                clean_lemma_for_label(sense["lemma"])
                for sense in senses
                if sense["lemma"].strip()
            }
        )

        candidate_concept_slug = candidate_slug_from_synset_id(
            synset_id
        )

        label = concept_label_from_synonyms(
            synonyms,
            fallback_slug=candidate_concept_slug,
        )

        definition = clean_definition(
            definitions_by_synset.get(
                synset_id,
                "",
            )
        )

        raw_synsets.append(
            {
                "source_slug": source_slug,
                "language_code": language_code,
                "synset_id": synset_id,
                "candidate_concept_slug": candidate_concept_slug,
                "label": label,
                "part_of_speech": pos_by_synset.get(
                    synset_id,
                    "",
                ),
                "definition": definition,
                "synonyms": "|".join(synonyms),
                "source_locator": synset_id,
                "review_status": "extracted",
            }
        )

        raw_relations.extend(
            relations_by_synset.get(
                synset_id,
                [],
            )
        )

        for sense in senses:
            raw_entries.append(
                {
                    "source_slug": source_slug,
                    "language_code": language_code,
                    "source_locator": (
                        f"{synset_id}#{sense['sense_id']}"
                    ),
                    "synset_id": synset_id,
                    "sense_id": sense["sense_id"],
                    "lemma": sense["lemma"],
                    "normalized_lemma": sense["normalized_lemma"],
                    "part_of_speech": (
                        sense["part_of_speech"]
                        or pos_by_synset.get(synset_id, "")
                    ),
                    "definition": definition,
                    "synonyms": "|".join(synonyms),
                    "lexical_entry_id": sense["lexical_entry_id"],
                    "extraction_confidence": "1.00",
                    "review_status": "extracted",
                }
            )

            if max_rows is not None and len(raw_entries) >= max_rows:
                return raw_entries, raw_synsets, raw_relations

    return raw_entries, raw_synsets, raw_relations


def write_raw_entries(
    rows: list[dict[str, str]],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=RAW_ENTRY_COLUMNS,
        )

        writer.writeheader()
        writer.writerows(rows)


def write_rows(
    rows: list[dict[str, str]],
    output_path: Path,
    columns: list[str],
) -> None:
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
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



def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Extract raw lexical entries from "
            "Open English Wordnet GWN-LMF XML."
        )
    )

    parser.add_argument(
        "--xml",
        type=Path,
        required=True,
        help="Path to english-wordnet XML or XML.GZ file.",
    )

    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to source_manifest.json.",
    )

    parser.add_argument(
        "--sample-terms",
        type=Path,
        help="Optional newline-separated sample lemmas.",
    )

    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory.",
    )

    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
    )

    args = parser.parse_args()

    manifest = load_manifest(args.manifest)

    raw_entries, raw_synsets, raw_relations = parse_oewn_xml_with_synsets(
        args.xml,
        source_slug=manifest["source_slug"],
        language_code=manifest["language_code"],
        sample_terms=load_sample_terms(args.sample_terms),
        max_rows=args.max_rows,
    )

    args.out.mkdir(
        parents=True,
        exist_ok=True,
    )

    write_rows(
        raw_entries,
        args.out / "raw_entries.csv",
        RAW_ENTRY_COLUMNS,
    )
    write_rows(
        raw_synsets,
        args.out / "raw_synsets.csv",
        RAW_SYNSET_COLUMNS,
    )
    write_rows(
        raw_relations,
        args.out / "raw_synset_relations.csv",
        RAW_SYNSET_RELATION_COLUMNS,
    )

    print(f"Wrote {len(raw_entries)} raw entries.")
    print(f"Wrote {len(raw_synsets)} raw synsets.")
    print(f"Wrote {len(raw_relations)} raw synset relations.")


if __name__ == "__main__":
    main()