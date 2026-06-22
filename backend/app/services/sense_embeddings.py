from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models.generated_name import Language
from app.models.semantic import Lexeme, Sense, SenseEmbedding
from app.utils.text import normalize_text
from app.services.embedding_provider import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
    embed_passage,
)


def build_sense_text(sense: Sense) -> str:
    lexeme = sense.lexeme
    language = lexeme.language

    tags = ", ".join(sense.raw_tags[:12])
    categories = ", ".join(sense.categories[:8])
    extra_glosses = "; ".join(sense.raw_glosses[1:4])

    return "\n".join(
        [
            f"word: {lexeme.lemma}",
            f"meaning of {lexeme.lemma}: {sense.definition}",
            f"definition: {sense.definition}",
            f"part of speech: {lexeme.part_of_speech}",
            f"language: {language.name}",
            f"additional glosses: {extra_glosses}",
            f"semantic tags: {tags}",
            f"dictionary categories: {categories}",
        ]
    ).strip()


def backfill_sense_embeddings(
    *,
    limit: int = 1000,
    commit_every: int = 100,
    language_code: str | None = None,
    replace_existing: bool = False,
    words: list[str] | None = None,
) -> int:
    created = 0

    with SessionLocal() as db:
        statement = (
            select(Sense)
            .options(selectinload(Sense.lexeme))
            .join(Lexeme, Lexeme.id == Sense.lexeme_id)
            .join(Language, Language.id == Lexeme.language_id)
            .where(Sense.visibility_status == "visible")
            .order_by(Sense.id)
            .limit(limit)
        )

        if not replace_existing:
            statement = (
                statement
                .outerjoin(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
                .where(SenseEmbedding.sense_id.is_(None))
            )

        if language_code is not None:
            statement = statement.where(Language.code == language_code)

        if words:
            normalized_words = [
                normalize_text(word)
                for word in words
                if normalize_text(word)
            ]

            statement = statement.where(
                Lexeme.normalized_lemma.in_(normalized_words)
            )

        senses = list(db.scalars(statement).all())

        for sense in senses:
            embedded_text = build_sense_text(sense)
            vector = embed_passage(embedded_text)

            if replace_existing:
                existing = db.get(SenseEmbedding, sense.id)

                if existing is not None:
                    db.delete(existing)
                    db.flush()

            db.add(
                SenseEmbedding(
                    sense_id=sense.id,
                    embedding_model=DEFAULT_EMBEDDING_MODEL,
                    embedding_dimensions=DEFAULT_EMBEDDING_DIMENSIONS,
                    embedded_text=embedded_text,
                    embedding=vector,
                )
            )

            created += 1

            if created % commit_every == 0:
                db.commit()
                print(f"Created {created} embeddings...", flush=True)

        db.commit()

    return created


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill embeddings for stored senses."
    )
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--commit-every", type=int, default=100)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete and recreate embeddings for the selected senses.",
    )
    parser.add_argument(
        "--words",
        nargs="*",
        default=None,
        help="Only embed senses for these lemmas.",
    )
    parser.add_argument(
        "--language-code",
        type=str,
        default=None,
        help="Only embed senses from this language code, such as en.",
    )

    args = parser.parse_args()

    created = backfill_sense_embeddings(
        limit=args.limit,
        commit_every=args.commit_every,
        language_code=args.language_code,
        replace_existing=args.replace,
        words=args.words,
    )

    print(f"Created {created} embeddings.")


if __name__ == "__main__":
    main()