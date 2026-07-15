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
from app.utils.text import normalize_lemma
from app.services.prune_taxonomy import Tier, classify, sole_alt_trigger


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


# ISO 15924 script per Wiktionary lang code, for the 20 planned languages.
# Display metadata only — never used in matching or classification.
LANGUAGE_SCRIPTS: dict[str, str] = {
    "en": "Latn", "hi": "Deva", "es": "Latn", "ru": "Cyrl", "la": "Latn",
    "el": "Grek", "sa": "Deva", "ang": "Latn", "non": "Latn", "pl": "Latn",
    "ar": "Arab", "he": "Hebr", "fa": "Arab", "ja": "Jpan", "zh": "Hani",
    "ko": "Kore", "cy": "Latn", "ga": "Latn", "de": "Latn", "sw": "Latn",
}


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
        script=LANGUAGE_SCRIPTS.get(code),
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
        normalized_lemma=normalize_lemma(word, language.code),
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
    dry_run: bool = False,
) -> dict[str, int]:
    input_path = input_path.expanduser().resolve()

    counts = {
        "entries_seen": 0,
        "entries_imported": 0,
        "entries_dropped_all_tier_a": 0,
        "lexemes_created_or_found": 0,
        "senses_created_visible": 0,
        "senses_created_hidden_tier_b": 0,
        "senses_created_provisional_alt": 0,
        "senses_dropped_tier_a": 0,
        "senses_skipped_existing": 0,
        "entries_without_senses": 0,
        "entries_without_word_or_pos": 0,
    }

    with SessionLocal() as db:
        # Always create/find the source row, dry-run or not. Nothing here is
        # ever committed unless dry_run is False (see the end of this block),
        # so a dry run is truly zero-write despite this call.
        source = get_or_create_source(db)

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

            # --- Tier gate: pre-classify every sense of this entry ---------
            classified: list[tuple[dict, list[str], str, Tier, bool]] = []
            for sense_data in senses:
                raw_glosses = [
                    str(g) for g in (
                        sense_data.get("glosses")
                        or sense_data.get("raw_glosses")
                        or []
                    )
                ]
                definition = raw_glosses[0].strip() if raw_glosses else ""
                tags = [str(t) for t in sense_data.get("tags", [])]
                tier = classify(pos, tags, word, definition)
                provisional = tier is Tier.A and sole_alt_trigger(
                    pos, tags, word, definition
                )
                classified.append(
                    (sense_data, raw_glosses, definition, tier, provisional)
                )

            keep = [c for c in classified if c[3] is not Tier.A or c[4]]
            if not keep:
                counts["entries_dropped_all_tier_a"] += 1
                counts["senses_dropped_tier_a"] += len(classified)
                continue
            # ----------------------------------------------------------------

            lang_code = str(entry.get("lang_code") or "unknown")
            lang_name = str(entry.get("lang") or lang_code)

            # Unconditional: language/lexeme are always concrete objects.
            # In a dry run these rows are created against the session but
            # rolled back at the very end, never committed.
            language = get_or_create_language(
                db, code=lang_code, name=lang_name,
            )
            lexeme = get_or_create_lexeme(
                db,
                language=language,
                source=source,
                entry=entry,
                entry_index=entry_index,
            )
            counts["lexemes_created_or_found"] += 1

            for sense_index, (sense_data, raw_glosses, definition,
                              tier, provisional) in enumerate(classified, start=1):
                if tier is Tier.A and not provisional:
                    counts["senses_dropped_tier_a"] += 1
                    continue

                if provisional:
                    visibility = "hidden"
                    counts["senses_created_provisional_alt"] += 1
                elif tier is Tier.B:
                    visibility = "hidden"
                    counts["senses_created_hidden_tier_b"] += 1
                else:
                    visibility = "visible"
                    counts["senses_created_visible"] += 1

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
                    if provisional:
                        counts["senses_created_provisional_alt"] -= 1
                    elif tier is Tier.B:
                        counts["senses_created_hidden_tier_b"] -= 1
                    else:
                        counts["senses_created_visible"] -= 1
                    continue

                db.add(Sense(
                    lexeme_id=lexeme.id,
                    source_id=source.id,
                    source_locator=locator,
                    sense_index=sense_index,
                    source_order=entry_index,
                    definition=definition,
                    raw_glosses=raw_glosses,
                    raw_tags=[str(t) for t in sense_data.get("tags", [])],
                    categories=[str(c) for c in sense_data.get("categories", [])],
                    examples=sense_data.get("examples") or [],
                    raw_sense=sense_data,
                    etymology_text=entry.get("etymology_text"),
                    visibility_status=visibility,
                    admin_status="normal",
                ))

            counts["entries_imported"] += 1

            if not dry_run and counts["entries_imported"] % commit_every == 0:
                db.commit()
                print(counts, flush=True)

            if limit is not None and counts["entries_imported"] >= limit:
                break

        if dry_run:
            db.rollback()
        else:
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and count only; write nothing to the database.",
    )

    args = parser.parse_args()

    counts = import_kaikki_file(
        input_path=args.input,
        limit=args.limit,
        commit_every=args.commit_every,
        dry_run=args.dry_run,
    )

    print("Import complete:")
    for key, value in counts.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()