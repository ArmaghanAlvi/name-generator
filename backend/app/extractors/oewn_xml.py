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


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]

    return tag


def open_text(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")

    return path.open("r", encoding="utf-8")


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
        help="Output raw_entries.csv path.",
    )

    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
    )

    args = parser.parse_args()

    manifest = load_manifest(args.manifest)

    rows = parse_oewn_xml(
        args.xml,
        source_slug=manifest["source_slug"],
        language_code=manifest["language_code"],
        sample_terms=load_sample_terms(args.sample_terms),
        max_rows=args.max_rows,
    )

    write_raw_entries(
        rows,
        args.out,
    )

    print(
        f"Wrote {len(rows)} raw entries to {args.out}"
    )


if __name__ == "__main__":
    main()