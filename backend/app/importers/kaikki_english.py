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
from app.models.semantic import (
    Lexeme,
    SenseCandidate,
    Source,
    UsableSense,
    UsableSenseSource,
)
from app.utils.text import normalize_text


CORE_POS = {
    "noun",
    "verb",
    "adj",
    "adjective",
    "adv",
    "adverb",
}

LOW_PRIORITY_POS = {
    "proper noun",
    "proper name",
    "abbrev",
    "abbreviation",
    "symbol",
    "punctuation",
    "letter",
    "character",
    "phrase",
    "proverb",
    "preposition",
    "conjunction",
    "determiner",
    "article",
    "pronoun",
    "interjection",
    "prefix",
    "suffix",
}

BAD_TAGS = {
    "vulgar",
    "offensive",
    "derogatory",
    "slur",
    "proscribed",
    "misspelling",
    "error",
}

LOW_PRIORITY_TAGS = {
    "obsolete",
    "archaic",
    "rare",
    "dialectal",
    "dated",
    "technical",
}


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open

    with opener(path, "rb") as file:
        for line in file:
            line = line.strip()

            if not line:
                continue

            yield orjson.loads(line)


def source_locator_for(
    *,
    word: str,
    pos: str,
    sense_index: int,
    gloss: str,
) -> str:
    digest = hashlib.sha1(
        f"{word}|{pos}|{sense_index}|{gloss}".encode("utf-8")
    ).hexdigest()[:16]

    return f"kaikki:en:{word}:{pos}:{sense_index}:{digest}"


def classify_candidate(
    *,
    pos: str,
    gloss: str,
    tags: list[str],
    categories: list[str],
    sense_count_for_entry: int,
) -> tuple[str, str, int, str]:
    """
    Return:
        review_status, review_tier, priority, review_reason
    """

    normalized_pos = pos.casefold()
    normalized_tags = {tag.casefold() for tag in tags}
    normalized_categories = {
        category.casefold()
        for category in categories
    }

    if not gloss.strip():
        return (
            "needs_edit",
            "human_review",
            100,
            "missing_gloss",
        )

    if normalized_tags & BAD_TAGS:
        return (
            "hidden",
            "low_priority",
            5,
            "bad_or_unsafe_tag",
        )

    if normalized_pos in LOW_PRIORITY_POS:
        return (
            "hidden",
            "low_priority",
            10,
            "low_priority_part_of_speech",
        )

    if normalized_tags & LOW_PRIORITY_TAGS:
        return (
            "hidden",
            "low_priority",
            20,
            "low_priority_tag",
        )

    if "taxonomic name" in normalized_categories:
        return (
            "hidden",
            "low_priority",
            10,
            "taxonomic_name",
        )

    if normalized_pos in CORE_POS and sense_count_for_entry == 1:
        return (
            "auto_accepted",
            "auto_usable",
            40,
            "single_clear_core_pos_sense",
        )

    if normalized_pos in CORE_POS:
        return (
            "pending_review",
            "human_review",
            80,
            "core_pos_multiple_senses",
        )

    return (
        "pending_review",
        "human_review",
        50,
        "normal_candidate",
    )


def get_or_create_language(db: Session) -> Language:
    language = db.scalar(
        select(Language).where(Language.code == "en")
    )

    if language is not None:
        return language

    language = Language(
        name="English",
        code="en",
        native_name="English",
        script="Latin",
    )
    db.add(language)
    db.flush()

    return language


def get_or_create_source(db: Session) -> Source:
    source = db.scalar(
        select(Source).where(Source.slug == "kaikki-en")
    )

    if source is not None:
        return source

    source = Source(
        slug="kaikki-en",
        name="Kaikki English Wiktionary Extract",
        source_type="dictionary_dump",
        url="https://kaikki.org/dictionary/English/",
        license="Wiktionary-derived; verify attribution/share-alike requirements before redistribution",
        notes=(
            "English machine-readable dictionary extracted from "
            "English Wiktionary via Wiktextract/Kaikki."
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
    word: str,
    pos: str,
    raw_language_name: str | None,
) -> Lexeme:
    normalized = normalize_text(word)

    lexeme = db.scalar(
        select(Lexeme).where(
            Lexeme.language_id == language.id,
            Lexeme.normalized_lemma == normalized,
            Lexeme.part_of_speech == pos,
            Lexeme.source_id == source.id,
        )
    )

    if lexeme is not None:
        return lexeme

    lexeme = Lexeme(
        language_id=language.id,
        lemma=word,
        normalized_lemma=normalized,
        part_of_speech=pos,
        source_id=source.id,
        source_entry_id=f"kaikki-en:{word}:{pos}",
        raw_language_name=raw_language_name,
    )
    db.add(lexeme)
    db.flush()

    return lexeme


def create_usable_sense_from_candidate(
    db: Session,
    *,
    candidate: SenseCandidate,
    review_status: str,
) -> None:
    existing = db.scalar(
        select(UsableSenseSource).where(
            UsableSenseSource.sense_candidate_id == candidate.id
        )
    )

    if existing is not None:
        return

    lexeme = candidate.lexeme
    label = lexeme.lemma
    short_definition = candidate.clean_gloss[:500]

    usable = UsableSense(
        lexeme_id=lexeme.id,
        label=label,
        definition=candidate.clean_gloss,
        short_definition=short_definition,
        usage_status="active",
        review_status=review_status,
        confidence=(
            "medium"
            if review_status == "auto_accepted"
            else "high"
        ),
        is_name_useful=True,
        is_root_useful=False,
    )
    db.add(usable)
    db.flush()

    db.add(
        UsableSenseSource(
            usable_sense_id=usable.id,
            sense_candidate_id=candidate.id,
            support_type="primary",
        )
    )


def import_kaikki_english(
    *,
    input_path: Path,
    limit: int | None = None,
    commit_every: int = 1000,
    create_auto_usable_senses: bool = True,
) -> dict[str, int]:
    counts = {
        "entries_seen": 0,
        "entries_imported": 0,
        "sense_candidates": 0,
        "auto_usable_senses": 0,
        "skipped_non_english": 0,
    }

    with SessionLocal() as db:
        language = get_or_create_language(db)
        source = get_or_create_source(db)
        db.commit()

        for entry in iter_jsonl(input_path):
            counts["entries_seen"] += 1

            lang_code = entry.get("lang_code")
            lang_name = entry.get("lang")

            if lang_code not in {None, "en"} and lang_name != "English":
                counts["skipped_non_english"] += 1
                continue

            word = (entry.get("word") or "").strip()
            pos = (entry.get("pos") or "").strip()

            if not word or not pos:
                continue

            senses = entry.get("senses") or []

            if not senses:
                continue

            lexeme = get_or_create_lexeme(
                db,
                language=language,
                source=source,
                word=word,
                pos=pos,
                raw_language_name=lang_name,
            )

            for sense_index, sense in enumerate(senses, start=1):
                glosses = sense.get("glosses") or sense.get("raw_glosses") or []

                if not glosses:
                    raw_gloss = ""
                else:
                    raw_gloss = str(glosses[0]).strip()

                clean_gloss = raw_gloss.strip()

                tags = [
                    str(tag)
                    for tag in sense.get("tags", [])
                ]

                categories = [
                    str(category)
                    for category in sense.get("categories", [])
                ]

                examples = sense.get("examples") or []

                locator = source_locator_for(
                    word=word,
                    pos=pos,
                    sense_index=sense_index,
                    gloss=clean_gloss,
                )

                existing = db.scalar(
                    select(SenseCandidate).where(
                        SenseCandidate.source_id == source.id,
                        SenseCandidate.source_locator == locator,
                    )
                )

                if existing is not None:
                    continue

                status, tier, priority, reason = classify_candidate(
                    pos=pos,
                    gloss=clean_gloss,
                    tags=tags,
                    categories=categories,
                    sense_count_for_entry=len(senses),
                )

                candidate = SenseCandidate(
                    lexeme_id=lexeme.id,
                    source_id=source.id,
                    source_locator=locator,
                    raw_gloss=raw_gloss,
                    clean_gloss=clean_gloss,
                    raw_tags=tags,
                    categories=categories,
                    examples=examples,
                    etymology_text=entry.get("etymology_text"),
                    review_status=status,
                    review_tier=tier,
                    priority=priority,
                    review_reason=reason,
                )
                db.add(candidate)
                db.flush()

                counts["sense_candidates"] += 1

                if (
                    create_auto_usable_senses
                    and status == "auto_accepted"
                ):
                    create_usable_sense_from_candidate(
                        db,
                        candidate=candidate,
                        review_status="auto_accepted",
                    )
                    counts["auto_usable_senses"] += 1

            counts["entries_imported"] += 1

            if counts["entries_imported"] % commit_every == 0:
                db.commit()
                print(counts)

            if limit is not None and counts["entries_imported"] >= limit:
                break

        db.commit()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import English senses from a Kaikki JSONL file."
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
        "--no-auto-usable",
        action="store_true",
    )

    args = parser.parse_args()

    counts = import_kaikki_english(
        input_path=args.input,
        limit=args.limit,
        commit_every=args.commit_every,
        create_auto_usable_senses=not args.no_auto_usable,
    )

    print("Import complete:")
    for key, value in counts.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()