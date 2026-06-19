from __future__ import annotations

import argparse
import gzip
import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import orjson
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.generated_name import Language
from app.models.semantic import Lexeme, Sense, Source
from app.utils.text import normalize_text


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open

    with opener(path, "rb") as file:
        for line in file:
            line = line.strip()

            if not line:
                continue

            yield orjson.loads(line)


def compact_entry_for_storage(entry: dict[str, Any]) -> dict[str, Any]:
    """
    Store the original entry, but avoid accidental mutation.
    This preserves Kaikki data for later admin/debug work.
    """
    return dict(entry)


def source_entry_id_for(entry: dict[str, Any], entry_index: int) -> str:
    word = str(entry.get("word") or "")
    pos = str(entry.get("pos") or "")
    lang_code = str(entry.get("lang_code") or "")
    etymology_number = str(entry.get("etymology_number") or "")

    digest = hashlib.sha1(
        f"{entry_index}|{lang_code}|{word}|{pos}|{etymology_number}".encode(
            "utf-8"
        )
    ).hexdigest()[:16]

    return f"kaikki:{lang_code or 'unknown'}:{word}:{pos}:{etymology_number}:{digest}"


def source_locator_for(
    *,
    entry: dict[str, Any],
    entry_index: int,
    sense_index: int,
    gloss: str,
) -> str:
    word = str(entry.get("word") or "")
    pos = str(entry.get("pos") or "")
    lang_code = str(entry.get("lang_code") or "")
    etymology_number = str(entry.get("etymology_number") or "")

    digest = hashlib.sha1(
        (
            f"{entry_index}|{lang_code}|{word}|{pos}|"
            f"{etymology_number}|{sense_index}|{gloss}"
        ).encode("utf-8")
    ).hexdigest()[:16]

    return (
        f"kaikki:{lang_code or 'unknown'}:{word}:"
        f"{pos}:{etymology_number}:{sense_index}:{digest}"
    )


def get_or_create_language(
    db: Session,
    *,
    code: str,
    name: str,
) -> Language:
    language = db.scalar(
        select(Language).where(Language.code == code)
    )

    if language is not None:
        return language

    language = Language(
        name=name,
        code=code,
        native_name=name,
        script=None,
    )
    db.add(language)
    db.flush()

    return language


def get_or_create_source(db: Session) -> Source:
    source = db.scalar(
        select(Source).where(Source.slug == "kaikki")
    )

    if source is not None:
        return source

    source = Source(
        slug="kaikki",
        name="Kaikki Wiktionary Extracts",
        source_type="dictionary_dump",
        url="https://kaikki.org/",
        license=(
            "Wiktionary-derived. Verify attribution and share-alike "
            "requirements before redistribution."
        ),
        notes=(
            "Machine-readable dictionaries extracted from Wiktionary "
            "using Wiktextract/Kaikki."
        ),
    )
    db.add(source)
    db.flush()

    return source


def get_or_create_lexeme(
    db: Session,
    *,
    language: Language,
    source: Source,
    entry: dict[str, Any],
    entry_index: int,
) -> Lexeme:
    word = str(entry.get("word") or "").strip()
    pos = str(entry.get("pos") or "").strip()
    source_entry_id = source_entry_id_for(entry, entry_index)

    existing = db.scalar(
        select(Lexeme).where(
            Lexeme.source_id == source.id,
            Lexeme.source_entry_id == source_entry_id,
        )
    )

    if existing is not None:
        return existing

    lexeme = Lexeme(
        language_id=language.id,
        lemma=word,
        normalized_lemma=normalize_text(word),
        part_of_speech=pos,
        source_id=source.id,
        source_entry_id=source_entry_id,
        raw_language_name=entry.get("lang"),
        raw_entry=compact_entry_for_storage(entry),
        import_status="active",
    )

    db.add(lexeme)
    db.flush()

    return lexeme


def import_kaikki_file(
    *,
    input_path: Path,
    limit: int | None = None,
    commit_every: int = 1000,
) -> dict[str, int]:
    input_path = input_path.expanduser().resolve()

    counts = {
        "entries_seen": 0,
        "entries_imported": 0,
        "lexemes_created_or_found": 0,
        "senses_created": 0,
        "senses_skipped_existing": 0,
        "entries_without_senses": 0,
        "entries_without_word_or_pos": 0,
    }

    with SessionLocal() as db:
        source = get_or_create_source(db)
        db.commit()

        for entry_index, entry in enumerate(iter_jsonl(input_path), start=1):
            counts["entries_seen"] += 1

            word = str(entry.get("word") or "").strip()
            pos = str(entry.get("pos") or "").strip()

            if not word or not pos:
                counts["entries_without_word_or_pos"] += 1
                continue

            senses = entry.get("senses") or []

            if not senses:
                counts["entries_without_senses"] += 1
                continue

            lang_code = str(entry.get("lang_code") or "unknown")
            lang_name = str(entry.get("lang") or lang_code)

            language = get_or_create_language(
                db,
                code=lang_code,
                name=lang_name,
            )

            lexeme = get_or_create_lexeme(
                db,
                language=language,
                source=source,
                entry=entry,
                entry_index=entry_index,
            )
            counts["lexemes_created_or_found"] += 1

            for sense_index, sense_data in enumerate(senses, start=1):
                raw_glosses = [
                    str(gloss)
                    for gloss in (
                        sense_data.get("glosses")
                        or sense_data.get("raw_glosses")
                        or []
                    )
                ]

                definition = raw_glosses[0].strip() if raw_glosses else ""

                locator = source_locator_for(
                    entry=entry,
                    entry_index=entry_index,
                    sense_index=sense_index,
                    gloss=definition,
                )

                existing = db.scalar(
                    select(Sense).where(
                        Sense.source_id == source.id,
                        Sense.source_locator == locator,
                    )
                )

                if existing is not None:
                    counts["senses_skipped_existing"] += 1
                    continue

                sense = Sense(
                    lexeme_id=lexeme.id,
                    source_id=source.id,
                    source_locator=locator,
                    sense_index=sense_index,
                    source_order=entry_index,
                    definition=definition,
                    raw_glosses=raw_glosses,
                    raw_tags=[
                        str(tag)
                        for tag in sense_data.get("tags", [])
                    ],
                    categories=[
                        str(category)
                        for category in sense_data.get("categories", [])
                    ],
                    examples=sense_data.get("examples") or [],
                    raw_sense=sense_data,
                    etymology_text=entry.get("etymology_text"),
                    visibility_status="visible",
                    admin_status="normal",
                )
                db.add(sense)
                counts["senses_created"] += 1

            counts["entries_imported"] += 1

            if counts["entries_imported"] % commit_every == 0:
                db.commit()
                print(counts, flush=True)

            if limit is not None and counts["entries_imported"] >= limit:
                break

        db.commit()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import a Kaikki JSONL/JSONL.GZ file with no prerequisite review."
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--commit-every",
        type=int,
        default=1000,
    )

    args = parser.parse_args()

    counts = import_kaikki_file(
        input_path=args.input,
        limit=args.limit,
        commit_every=args.commit_every,
    )

    print("Import complete:")
    for key, value in counts.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()