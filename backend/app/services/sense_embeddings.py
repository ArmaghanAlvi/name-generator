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


# Only these Kaikki relation arrays carry MEANING-equivalence. Everything else
# (related, derived, hypernyms, coordinate_terms) encodes TOPIC association,
# which — as the 'light' entry data proved — drags vectors toward domain
# clusters (physics) rather than synonym clusters. Never embed those.
_EMBEDDABLE_SYNONYM_KEYS = ("synonyms",)


def _kaikki_sense_level_synonyms(sense: Sense) -> list[str]:
    """Synonyms attached directly to THIS sense — highest precision."""
    raw = sense.raw_sense or {}
    out: list[str] = []
    for key in _EMBEDDABLE_SYNONYM_KEYS:
        for item in raw.get(key) or []:
            if isinstance(item, dict):
                word = str(item.get("word") or "").strip()
            elif isinstance(item, str):
                word = item.strip()
            else:
                word = ""
            # Skip multi-word and obviously non-name synonyms for embedding;
            # they add noise to the vector. (They can still live in
            # SenseRelation for the lexical tier.)
            if word and " " not in word:
                out.append(word)
    return out


def _kaikki_entry_level_synonyms(sense: Sense) -> list[str]:
    """
    Entry-level synonyms, routed to this sense by Wiktextract's 'sense:'
    hint string when present. Falls back to including a synonym when it
    carries no hint (applies entry-wide). This is what gives 'light' its
    'visible light'/'luminance' without smearing them across all 60 senses.
    """
    lexeme = sense.lexeme
    raw_entry = lexeme.raw_entry or {}
    def_tokens = set(normalize_text(sense.definition).split())

    out: list[str] = []
    for key in _EMBEDDABLE_SYNONYM_KEYS:
        for item in raw_entry.get(key) or []:
            if not isinstance(item, dict):
                continue
            word = str(item.get("word") or "").strip()
            if not word or " " in word:
                continue
            hint = item.get("sense")
            if hint:
                hint_tokens = set(normalize_text(str(hint)).split())
                # route only if the hint overlaps this sense's definition
                if hint_tokens and not (hint_tokens & def_tokens):
                    continue
            out.append(word)
    return out


def _oewn_synonyms_from_relations(sense: Sense) -> list[str]:
    """
    OEWN synset-mates previously materialized into sense.relations by the
    Stage 4 import (relation_type == 'synonym', provenance OEWN). This is the
    anchor source for words Kaikki left orphaned, like 'radiance'.

    Requires the Sense.relations relationship to be loaded by the caller
    (selectinload) so this stays a pure in-memory read during bulk embed.
    """
    out: list[str] = []
    for rel in getattr(sense, "relations", []) or []:
        if rel.relation_type == "synonym":
            word = (rel.target_text or "").strip()
            if word and " " not in word:
                out.append(word)
    return out


def collect_synonyms_for_embedding(sense: Sense, limit: int = 10) -> list[str]:
    """
    Union of synonym sources in priority order, de-duplicated, single-word,
    excluding the lemma itself. Sense-level Kaikki first (most precise),
    then entry-level Kaikki (sense-routed), then OEWN synset-mates (breadth /
    orphan rescue). Capped so the synonym line can't dominate the vector.
    """
    lemma_norm = normalize_text(sense.lexeme.lemma)
    seen: set[str] = set()
    ordered: list[str] = []

    for source in (
        _kaikki_sense_level_synonyms(sense),
        _kaikki_entry_level_synonyms(sense),
        _oewn_synonyms_from_relations(sense),
    ):
        for word in source:
            norm = normalize_text(word)
            if not norm or norm == lemma_norm or norm in seen:
                continue
            seen.add(norm)
            ordered.append(word)
            if len(ordered) >= limit:
                return ordered

    return ordered


def build_sense_text(sense: Sense) -> str:
    """
    Text we embed for a stored sense.

    Shape (parallel to the query text in vector_sense_search):
        "<lemma>: <definition>; <extra glosses>; synonyms: a, b, c"

    - Lead with lemma + definition so the vector encodes meaning.
    - Drop dictionary categories/tags entirely (topic noise).
    - Append synonyms ONLY (never related/derived/hypernyms), unioned from
      Kaikki sense-level, Kaikki entry-level, and OEWN synset-mates. This is
      what moves orphan words like 'radiance' into the illumination cluster.
    """
    lexeme = sense.lexeme
    fragments: list[str] = [f"{lexeme.lemma}: {sense.definition}"]

    extra_glosses = "; ".join(sense.raw_glosses[1:3])
    if extra_glosses:
        fragments.append(extra_glosses)

    synonyms = collect_synonyms_for_embedding(sense)
    if synonyms:
        fragments.append("synonyms: " + ", ".join(synonyms))

    return " ".join(fragments).strip()


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