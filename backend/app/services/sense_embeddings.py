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
from app.services.prune_taxonomy import Tier, classify_sense

# Only these Kaikki relation arrays carry MEANING-equivalence. Everything else
# (related, derived, hypernyms, coordinate_terms) encodes TOPIC association,
# which — as the 'light' entry data proved — drags vectors toward domain
# clusters (physics) rather than synonym clusters. Never embed those.
_EMBEDDABLE_SYNONYM_KEYS = ("synonyms",)


def is_name_worthy(sense: Sense) -> bool:
    """
    True if this sense should be embedded as a name candidate — i.e. Tier C in
    the shared pruning taxonomy. Deferred entirely to prune_taxonomy so the
    embedder, the purge, and the importer enforce one definition.
    """
    return classify_sense(sense) is Tier.C


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


# Provenances whose synonym edges may BAKE INTO embedding text.
# awn4 is deliberately EXCLUDED: it is AI-translated (distinct provenance
# tier so ranking can discount it) — a synonym baked into the vector cannot
# be discounted later. Its edges still live in sense_relations for the
# lexical tier; they just never shape a vector.
_EMBEDDABLE_EDGE_PROVENANCES = frozenset({"kaikki", "oewn", "omw-ja", "omw-arb"})


def _relation_synonyms(sense: Sense) -> list[str]:
    """
    Synonym-relation targets previously materialized into sense.relations
    (OEWN for English; omw-ja / omw-arb for the new languages), filtered by
    the embeddable-provenance allowlist. This is the anchor source for words
    the language's Kaikki edges left orphaned, like 'radiance'.

    Requires Sense.relations loaded by the caller (selectinload) so this
    stays a pure in-memory read during bulk embed.
    """
    out: list[str] = []
    for rel in getattr(sense, "relations", []) or []:
        if (
            rel.relation_type == "synonym"
            and rel.provenance in _EMBEDDABLE_EDGE_PROVENANCES
        ):
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
        _relation_synonyms(sense),
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
    """
    `limit` is now the WINDOW SIZE, not a total cap: the loop pages through
    all matching senses by id-cursor until exhausted, one window at a time.
    (The old semantics — first `limit` unembedded senses, re-invoke to
    continue — breaks once any sense can be SKIPPED without being embedded:
    skipped rows re-enter every window, and an all-skipped window reads as
    'done' while unembedded senses remain beyond it.)
    """
    created = 0
    skipped_bare = 0

    with SessionLocal() as db:
        if replace_existing and language_code is not None:
            from sqlalchemy import delete as _sa_delete
            sub = (
                select(SenseEmbedding.sense_id)
                .join(Sense, Sense.id == SenseEmbedding.sense_id)
                .join(Lexeme, Lexeme.id == Sense.lexeme_id)
                .join(Language, Language.id == Lexeme.language_id)
                .where(Language.code == language_code)
            )
            n = db.execute(
                _sa_delete(SenseEmbedding).where(SenseEmbedding.sense_id.in_(sub))
            ).rowcount  # type: ignore[attr-defined]
            db.commit()
            print(f"[replace] cleared {n} existing embeddings for {language_code}")

        from app.services.embedding_provider import embed_passages

        normalized_words = None
        if words:
            normalized_words = [
                normalize_text(word) for word in words if normalize_text(word)
            ]

        last_id = 0
        while True:
            statement = (
                select(Sense)
                .options(
                    selectinload(Sense.lexeme),
                    selectinload(Sense.relations),
                )
                .join(Lexeme, Lexeme.id == Sense.lexeme_id)
                .join(Language, Language.id == Lexeme.language_id)
                .where(
                    Sense.visibility_status == "visible",
                    Sense.id > last_id,
                )
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
            if normalized_words:
                statement = statement.where(
                    Lexeme.normalized_lemma.in_(normalized_words)
                )

            senses = list(db.scalars(statement).all())
            if not senses:
                break
            last_id = senses[-1].id

            worthy: list[Sense] = []
            texts: list[str] = []
            for s in senses:
                if not is_name_worthy(s):
                    continue
                text = build_sense_text(s)
                # Skip pure-lemma senses: no gloss AND no synonyms. A bare
                # lemma still lands SOMEWHERE in E5 space, and meaning-free
                # points pollute the nearest-neighbor surface that root
                # fallback will query. Senses with synonyms-but-no-gloss
                # still carry real signal and DO embed.
                if not (s.definition or "").strip() and "synonyms:" not in text:
                    skipped_bare += 1
                    continue
                worthy.append(s)
                texts.append(text)

            BATCH = 256
            for start in range(0, len(worthy), BATCH):
                chunk = worthy[start:start + BATCH]
                chunk_texts = texts[start:start + BATCH]
                vectors = embed_passages(chunk_texts)
                for sense, text, vector in zip(chunk, chunk_texts, vectors):
                    db.add(SenseEmbedding(
                        sense_id=sense.id,
                        embedding_model=DEFAULT_EMBEDDING_MODEL,
                        embedding_dimensions=DEFAULT_EMBEDDING_DIMENSIONS,
                        embedded_text=text,
                        embedding=vector,
                    ))
                    created += 1
                db.commit()
                print(f"Created {created} embeddings...", flush=True)

            db.expunge_all()  # release the window's identity map (raw_entry is heavy)

    print(f"Skipped {skipped_bare} bare senses (no gloss, no synonyms).")
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