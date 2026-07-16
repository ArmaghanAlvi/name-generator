"""
Reads Lexeme.raw_entry (entry-level synonym/relation lists already stored at
import time) and writes edges into sense_relations with provenance='kaikki'.
No re-download. Idempotent via uq_sense_relations_edge + an in-memory set.

⟲ REVISED: an earlier version of this module read entry-level relations only,
on the claim that sense-level raw_sense carries no 'synonyms' key. That claim
was checked against insufficient evidence and is false in aggregate: EN
sense-level refs (252,878) outnumber entry-level (34,878) 7.3x; AR sense-level
(6,720) outnumbers entry-level (542) 12.4x. Sense-level relations are read
directly via sense_index (exact, since import_kaikki_file enumerates raw
senses in the same order) with no routing guesswork needed. Entry-level
relations remain, since ~1-3% of entries carry relations at both levels, and
are routed back to senses three ways:
  1. an item 'sense:' hint string  -> token-overlap against sense.definition
  2. a Wiktextract '_dis1' weight vector (positional over the entry's senses
     in sense_index order) -> attach to senses near the top weight
  3. neither / all-zero _dis1          -> broad attach to all senses

Only 'synonym' and 'coordinate' edges are later read by the embedding text;
the rest are stored for the lexical tier / debugging and must never enter
embedding text (that gate lives in sense_embeddings.py, not here).
"""

import argparse

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models.semantic import Lexeme, Sense, SenseRelation, Source
from app.models.generated_name import Language
from app.utils.text import normalize_lemma as _canonical_normalize_lemma


# Kaikki entry-level key -> our constrained relation_type
# (must stay within ck_sense_relations_type)
RELATION_MAP = {
    "synonyms": "synonym",
    "coordinate_terms": "coordinate",
    "antonyms": "antonym",
    "hypernyms": "hypernym",
    "hyponyms": "hyponym",
    "derived": "derived",
    "related": "related",
}

# How close to the top _dis1 weight a sense must score to receive the edge.
DIS1_KEEP_RATIO = 0.6

# Only these relation types feed the embedding text (Stage 5), so only these
# get sense-level routing. All others attach to the primary sense.
EMBED_SAFE = {"synonym", "coordinate"}

KAIKKI_SOURCE_SLUG = "kaikki"


def normalize_lemma(text: str, lang_code: str | None = None) -> str:
    """Delegates to the canonical key in app.utils.text — never fork this.

    lang_code is REQUIRED for anything written to target_normalized: it must
    match the policy used for Lexeme.normalized_lemma (importer passes
    language.code), or the join silently fails. Only the _route() token-overlap
    path may omit it — that operates on English gloss text, not join keys.
    """
    return _canonical_normalize_lemma(text, lang_code)


def _get_or_create_kaikki_source(db) -> Source:
    src = db.scalars(
        select(Source).where(Source.slug == KAIKKI_SOURCE_SLUG)
    ).first()
    if src is None:
        src = Source(
            slug=KAIKKI_SOURCE_SLUG,
            name="Kaikki (Wiktextract)",
            source_type="wiktionary",
        )
        db.add(src)
        db.commit()
        db.refresh(src)
    return src


def _route(item: dict, senses_ordered: list[Sense]) -> list[Sense]:
    """Decide which senses an entry-level relation item attaches to.

    Priority: explicit 'sense:' hint (token overlap) -> positional _dis1
    weights -> fallback to the PRIMARY sense only (lowest sense_index).

    The fallback is deliberately the single primary sense, NOT all senses:
    an unroutable entry-level synonym is far more likely to concern the
    word's main meaning than its minor senses, and broad-attaching to every
    sense floods the ~10-cap embedding union with noise. OEWN (Stage 3)
    supplies precision for the minor/orphan senses instead.
    """
    # 1. explicit sense hint -> token overlap with definition
    hint = (item.get("sense") or "").strip()
    if hint:
        hint_tokens = set(normalize_lemma(hint).split())
        scored = []
        for s in senses_ordered:
            def_tokens = set(normalize_lemma(s.definition or "").split())
            overlap = len(hint_tokens & def_tokens)
            if overlap:
                scored.append((overlap, s))
        if scored:
            best = max(ov for ov, _ in scored)
            return [s for ov, s in scored if ov == best]
        # hint present but no overlap -> fall through

    # 2. _dis1 weight vector, positional over senses in sense_index order
    dis = item.get("_dis1")
    if dis:
        try:
            weights = [int(x) for x in dis.split()]
        except (ValueError, AttributeError):
            weights = []
        if weights and any(weights) and len(weights) == len(senses_ordered):
            mx = max(weights)
            return [
                s
                for s, w in zip(senses_ordered, weights)
                if w >= DIS1_KEEP_RATIO * mx
            ]
        # length mismatch (e.g. _dis1 has 24 weights, lexeme has 20 senses)
        # or all-zero -> not usable, fall through

    # 3. fallback: primary sense only (lowest sense_index)
    return [senses_ordered[0]]


def backfill(language_code: str, commit_every: int) -> None:
    with SessionLocal() as db:
        source = _get_or_create_kaikki_source(db)

        lang = db.scalars(
            select(Language).where(Language.code == language_code)
        ).first()
        if lang is None:
            raise SystemExit(f"No Language row with code={language_code!r}")

        # (language_id, normalized_lemma) -> lexeme_id, for target resolution.
        # normalized_lemma is NOT globally unique (per-language indexes only),
        # so the language_id MUST be part of the key.
        lex_index: dict[tuple[int, str], int] = {}
        for lid, lang_id, norm in db.execute(
            select(Lexeme.id, Lexeme.language_id, Lexeme.normalized_lemma)
        ).all():
            lex_index[(lang_id, norm)] = lid

        existing_edges: set[tuple[int, str, str, str]] = set()
        out: list[SenseRelation] = []
        total = 0
        page_size = 2000
        last_id = 0

        while True:
            # Fetch one page of lexemes by ascending id, fully materialized
            # (no open server-side cursor, so mid-loop commits are safe).
            page = db.scalars(
                select(Lexeme)
                .where(Lexeme.language_id == lang.id, Lexeme.id > last_id)
                .order_by(Lexeme.id)
                .limit(page_size)
                .options(selectinload(Lexeme.senses))
            ).all()

            if not page:
                break

            for lex in page:
                last_id = lex.id
                senses_ordered = sorted(lex.senses, key=lambda s: s.sense_index)
                if not senses_ordered:
                    continue

                raw = lex.raw_entry or {}

                # --- Sense-level relations (the majority signal; see Stage
                # 4.6 finding: en sense-level 252,878 vs entry-level 34,878;
                # ar sense-level 6,720 vs entry-level 542). sense_index is
                # the 1-based position of a Sense in the entry's RAW senses
                # list (import_kaikki_file enumerates unfiltered senses), so
                # this mapping is exact -- no _route() guessing needed.
                sense_by_index = {s.sense_index: s for s in senses_ordered}
                raw_senses = raw.get("senses") or []
                for pos, sd in enumerate(raw_senses, start=1):
                    sense = sense_by_index.get(pos)
                    if sense is None:
                        continue  # this raw sense was pruned; nothing to attach to
                    for kaikki_key, rel_type in RELATION_MAP.items():
                        for item in sd.get(kaikki_key, []) or []:
                            if not isinstance(item, dict):
                                continue
                            word = item.get("word")
                            if not word:
                                continue
                            norm = normalize_lemma(word, lang.code)
                            if not norm:
                                continue
                            target_lexeme_id = lex_index.get((lang.id, norm))
                            key = (sense.id, rel_type, "kaikki", norm)
                            if key in existing_edges:
                                continue
                            existing_edges.add(key)
                            out.append(
                                SenseRelation(
                                    from_sense_id=sense.id,
                                    relation_type=rel_type,
                                    provenance="kaikki",
                                    target_text=word[:300],
                                    target_normalized=norm[:300],
                                    target_sense_hint=(item.get("sense") or "").strip() or None,
                                    target_lexeme_id=target_lexeme_id,
                                    source_id=source.id,
                                )
                            )

                # --- Entry-level relations (existing path) ---
                for kaikki_key, rel_type in RELATION_MAP.items():
                    for item in raw.get(kaikki_key, []) or []:
                        if not isinstance(item, dict):
                            continue
                        word = item.get("word")
                        if not word:
                            continue
                        norm = normalize_lemma(word, lang.code)
                        if not norm:
                            continue

                        hint = (item.get("sense") or "").strip() or None
                        target_lexeme_id = lex_index.get((lang.id, norm))

                        # Only embedding-relevant relations get sense-level
                        # routing. Others (hyponym/derived/hypernym/related/
                        # antonym) attach to the primary sense: nothing reads
                        # them per-sense today, and _dis1-spreading a 1500-item
                        # hyponym list fabricates precision the data lacks.
                        if rel_type in EMBED_SAFE:
                            targets = _route(item, senses_ordered)
                        else:
                            targets = [senses_ordered[0]]
                        for sense in targets:
                            key = (sense.id, rel_type, "kaikki", norm)
                            if key in existing_edges:
                                continue
                            existing_edges.add(key)
                            out.append(
                                SenseRelation(
                                    from_sense_id=sense.id,
                                    relation_type=rel_type,
                                    provenance="kaikki",
                                    target_text=word[:300],
                                    target_normalized=norm[:300],
                                    target_sense_hint=hint,
                                    target_lexeme_id=target_lexeme_id,
                                    source_id=source.id,
                                )
                            )

            if len(out) >= commit_every:
                db.add_all(out)
                db.commit()
                total += len(out)
                print(f"committed ~{total} edges (through lexeme id {last_id})")
                out = []

        if out:
            db.add_all(out)
            db.commit()
            total += len(out)

        print(f"done: {total} kaikki edges")


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill sense_relations from Kaikki raw JSON.")
    ap.add_argument("--language-code", default="en")
    ap.add_argument("--commit-every", type=int, default=1000)
    args = ap.parse_args()
    backfill(args.language_code, args.commit_every)


if __name__ == "__main__":
    main()