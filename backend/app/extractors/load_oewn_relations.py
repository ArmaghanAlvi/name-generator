"""
Reads the FULL extraction CSVs produced by oewn_xml.py:
  - raw_entries.csv          (one row per synset-member: lemma, pos,
                              definition, synset_id, and the synset's
                              pipe-joined `synonyms` list)
  - raw_synset_relations.csv (source_synset_id, target_synset_id,
                              relationship_type)

Writes provenance='oewn' edges:
  - synonym       : each synset member -> the other members of its synset
  - near_synonym  : members of synsets joined by `similar` (and, optionally,
                    hypernym) relations

Matching an OEWN member to one of our Sense rows:
  1. normalized_lemma equality  (BOTH sides normalized with normalize_text /
                                 NFKC, so non-ASCII lemmas match correctly)
  2. POS map  n/v/a/r/s -> noun/verb/adj/adv/adj
  3. attach to the PRIMARY sense (lowest sense_index). Per-sense routing by
     definition-token overlap was tried and removed: independently-authored
     OEWN vs Kaikki glosses rarely share enough content words to route
     reliably, and Stage 6 reads synonyms off the *selected* sense at query
     time — so fragmenting the inventory across senses hurts recall. Sense
     disambiguation is done downstream by embeddings (Stage 5) + search-time
     sense selection (Stage 6), not here.

Idempotent via uq_sense_relations_edge + an in-memory existing_edges set.
"""

import argparse
import csv
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import SessionLocal
from app.models.semantic import Lexeme, Sense, SenseRelation, Source
from app.models.generated_name import Language
from app.utils.text import normalize_text   # SAME normalizer the CSV used (NFKC)


OEWN_SOURCE_SLUG = "oewn-2025"

# OEWN GWN-LMF part-of-speech -> our Kaikki-style part_of_speech strings.
# 's' = satellite adjective -> adj.
OEWN_POS_MAP = {
    "n": "noun",
    "v": "verb",
    "a": "adj",
    "s": "adj",
    "r": "adv",
}

# Synset-relation types we treat as near-synonymy. Confirm against the
# relType histogram from Stage 3a-iii before trusting this set.
NEAR_SYNONYM_RELTYPES = {"similar"}


def _pos_from_oewn(raw_pos: str) -> str | None:
    return OEWN_POS_MAP.get((raw_pos or "").strip().lower())


def _get_or_create_oewn_source(db) -> Source:
    src = db.scalars(
        select(Source).where(Source.slug == OEWN_SOURCE_SLUG)
    ).first()
    if src is None:
        src = Source(
            slug=OEWN_SOURCE_SLUG,
            name="Open English WordNet 2025",
            source_type="wordnet",
        )
        db.add(src)
        db.commit()
        db.refresh(src)
    return src


def _build_sense_index(db, language_id: int):
    """
    (normalized_lemma_NFKC, our_pos) -> list[Sense], for routing.

    Both keys pass through normalize_text so they line up with the OEWN CSV,
    whose normalized_lemma was produced by the same function.
    """
    index: dict[tuple[str, str], list[Sense]] = defaultdict(list)
    rows = db.execute(
        select(Sense, Lexeme.normalized_lemma, Lexeme.part_of_speech)
        .join(Lexeme, Lexeme.id == Sense.lexeme_id)
        .where(
            Lexeme.language_id == language_id,
            Sense.visibility_status == "visible",
        )
    ).all()
    for sense, norm_lemma, pos in rows:
        key = (normalize_text(norm_lemma), (pos or "").strip().lower())
        index[key].append(sense)
    # keep each list ordered by sense_index so [0] is the primary sense
    for key in index:
        index[key].sort(key=lambda s: s.sense_index)
    return index


def _primary_sense(senses: list[Sense]) -> Sense | None:
    """Return the primary sense (lowest sense_index), or None if no match.

    OEWN synonyms attach to the primary sense rather than being routed per
    sense. Definition-token overlap between OEWN and Kaikki glosses proved too
    weak to route reliably, and Stage 6 reads synonyms off the *selected* sense
    at query time — so a complete per-lexeme inventory on the primary sense
    gives better recall than a fragmented one. Disambiguation is downstream
    (embeddings + search-time sense selection), not here.
    """
    if not senses:
        return None
    return senses[0]   # senses pre-sorted by sense_index


def _read_entries(path: str):
    """
    raw_entries.csv -> dict keyed by synset_id, each value a list of member
    dicts {normalized_lemma, lemma, our_pos, synonyms:set[str], definition}.
    Skips members whose POS doesn't map.
    """
    by_synset: dict[str, list[dict]] = defaultdict(list)
    synset_def: dict[str, str] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            our_pos = _pos_from_oewn(row["part_of_speech"])
            if our_pos is None:
                continue
            synset_id = row["synset_id"]
            synset_def[synset_id] = row.get("definition", "")
            members = [m for m in (row.get("synonyms") or "").split("|") if m]
            by_synset[synset_id].append(
                {
                    "normalized_lemma": normalize_text(row["normalized_lemma"]),
                    "lemma": row["lemma"],
                    "our_pos": our_pos,
                    "members": members,
                    "definition": row.get("definition", ""),
                }
            )
    return by_synset, synset_def


def load(synsets_csv: str, relations_csv: str, commit_every: int) -> None:
    with SessionLocal() as db:
        source = _get_or_create_oewn_source(db)
        lang = db.scalars(select(Language).where(Language.code == "en")).first()
        if lang is None:
            raise SystemExit("No Language row with code='en'")

        sense_index = _build_sense_index(db, lang.id)

        # lemma(NFKC) -> lexeme_id, for target_lexeme_id resolution
        lex_resolve: dict[str, int] = {}
        from sqlalchemy import exists  # move to top-of-file imports

        for lid, norm in db.execute(
            select(Lexeme.id, Lexeme.normalized_lemma)
            .where(
                Lexeme.language_id == lang.id,
                exists().where(
                    Sense.lexeme_id == Lexeme.id,
                    Sense.visibility_status == "visible",
                ),
            )
        ).all():
            lex_resolve.setdefault(normalize_text(norm), lid)

        by_synset, synset_def = _read_entries(synsets_csv)

        existing_edges: set[tuple[int, str, str, str]] = set()
        out: list[dict] = []
        total = 0

        def flush(rows):
            if not rows:
                return
            stmt = pg_insert(SenseRelation).values(rows)
            stmt = stmt.on_conflict_do_nothing(
                constraint="uq_sense_relations_edge"
            )
            db.execute(stmt)
            db.commit()

        def queue_edge(from_sense, rel_type, target_lemma):
            norm = normalize_text(target_lemma)
            if not norm:
                return
            key = (from_sense.id, rel_type, "oewn", norm)
            if key in existing_edges:
                return
            existing_edges.add(key)
            out.append(
                {
                    "from_sense_id": from_sense.id,
                    "relation_type": rel_type,
                    "provenance": "oewn",
                    "target_text": target_lemma[:300],
                    "target_normalized": norm[:300],
                    "target_sense_hint": None,
                    "target_lexeme_id": lex_resolve.get(norm),
                    "source_id": source.id,
                }
            )

        # ---- synonym edges: members of the same synset ----
        for synset_id, members in by_synset.items():
            for member in members:
                others = [m for m in member["members"]
                          if normalize_text(m) != member["normalized_lemma"]]
                if not others:
                    continue  # singleton synset, nothing to link
                senses = sense_index.get(
                    (member["normalized_lemma"], member["our_pos"])
                )
                target_sense = _primary_sense(senses or [])
                if target_sense is None:
                    continue  # this OEWN lemma isn't one of our senses
                for other in others:
                    queue_edge(target_sense, "synonym", other)

            if len(out) >= commit_every:
                flush(out)
                total += len(out); print(f"committed ~{total} oewn edges"); out = []

        # ---- near_synonym edges: synsets joined by `similar` ----
        # Build synset_id -> set of member lemmas for target expansion.
        members_of: dict[str, list[str]] = {
            sid: sorted({m for mem in mems for m in mem["members"]})
            for sid, mems in by_synset.items()
        }

        def attach_near_synonyms(from_synset, to_synset):
            """Attach near_synonym edges from from_synset's senses to
            to_synset's member lemmas."""
            target_lemmas = members_of.get(to_synset, [])
            if not target_lemmas:
                return
            for member in by_synset.get(from_synset, []):
                senses = sense_index.get(
                    (member["normalized_lemma"], member["our_pos"])
                )
                target_sense = _primary_sense(senses or [])
                if target_sense is None:
                    continue
                for tl in target_lemmas:
                    if normalize_text(tl) == member["normalized_lemma"]:
                        continue
                    queue_edge(target_sense, "near_synonym", tl)

        with open(relations_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["relationship_type"].strip().lower() not in NEAR_SYNONYM_RELTYPES:
                    continue
                src_syn = row["source_synset_id"]
                tgt_syn = row["target_synset_id"]
                # symmetric: similar(A,B) means A's senses get B's lemmas
                # AND B's senses get A's lemmas. The in-memory existing_edges
                # set dedups if OEWN also emits the mirrored row.
                attach_near_synonyms(src_syn, tgt_syn)
                attach_near_synonyms(tgt_syn, src_syn)

                if len(out) >= commit_every:
                    flush(out)
                    total += len(out); print(f"committed ~{total} oewn edges"); out = []

        flush(out)
        total += len(out)
        print(f"done: {total} oewn edges")


def main() -> None:
    ap = argparse.ArgumentParser(description="Load OEWN relations into sense_relations.")
    ap.add_argument("--synsets", required=True, help="raw_entries.csv path")
    ap.add_argument("--relations", required=True, help="raw_synset_relations.csv path")
    ap.add_argument("--commit-every", type=int, default=2000)
    args = ap.parse_args()
    load(args.synsets, args.relations, args.commit_every)


if __name__ == "__main__":
    main()