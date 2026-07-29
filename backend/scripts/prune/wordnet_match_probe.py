"""
Wordnet <-> Kaikki match probe (read-only, NO DB queries) — Phase B6, pre-import.

WHY THIS EXISTS
---------------
`wordnet_lmf.py` dry-run prints the matched-size histogram and attachable-edge
count, but it reads the DB — so it only runs AFTER the language is imported.
B6 has to decide "is this wordnet worth importing at all" BEFORE Phase C.
This probe predicts the importer's numbers from the two FILES, reusing the
importer's own parser (`parse_lmf`) and the real `classify()`, so the
prediction cannot drift from the pipeline it predicts:

  * a member joins only if a Kaikki VISIBLE (Tier C) sense exists with the same
    (normalize_lemma(lemma, lang), POS) key -- `sense_of` in wordnet_lmf.run()
    is built from visible senses only;
  * a synset with fewer than 2 members emits ZERO synonym edges
    (density beats breadth -- the awn4 lesson);
  * membership rows are emitted only for synsets carrying an INDEXED ili.

Also reports `hidden_only`: members whose key exists in the Kaikki file but
only on a Tier-A/B sense. That is what the prune taxonomy costs this wordnet,
and it is the cross-check on the rule-7 / rule-12 fixes.

Requires the backend venv (it imports app.*; the DB engine is configured from
.env but never connected -- no query is issued anywhere in this file).

USAGE (from backend/):
  python3 scripts/prune/wordnet_match_probe.py \
      --kaikki ~/Personal-Projects/datasets/kaikki/kaikki-German.jsonl.gz \
      --lmf ~/Personal-Projects/datasets/wordnets/odenet/deWordNet.xml \
      --lang-code de [--join-marker] [--limit N] [--examples N]
"""
from __future__ import annotations

import argparse
import gzip
import os
import sys
from collections import Counter
from pathlib import Path

import orjson

sys.path.insert(0, os.getcwd())

from app.importers.wordnet_lmf import _hist, parse_lmf   # noqa: E402
from app.services.prune_taxonomy import Tier, classify   # noqa: E402
from app.utils.text import normalize_lemma               # noqa: E402


def iter_jsonl(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield orjson.loads(line)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kaikki", type=Path, required=True)
    ap.add_argument("--lmf", type=Path, required=True)
    ap.add_argument("--lang-code", required=True,
                    help="OUR language code (de, es, zh ...), not the file's")
    ap.add_argument("--join-marker", action="store_true",
                    help="strip '+' morpheme markers (omw-ja convention)")
    ap.add_argument("--limit", type=int, default=None, help="max Kaikki entries")
    ap.add_argument("--examples", type=int, default=10)
    args = ap.parse_args()

    kpath = args.kaikki.expanduser().resolve()
    lpath = args.lmf.expanduser().resolve()
    lang = args.lang_code
    cap = args.examples

    # ---- pass 1: the Kaikki side, classified exactly as the importer would ---
    visible_keys: set[tuple[str, str]] = set()
    any_keys: set[tuple[str, str]] = set()
    entries = 0
    for entry in iter_jsonl(kpath):
        if args.limit is not None and entries >= args.limit:
            break
        entries += 1
        word = str(entry.get("word") or "").strip()
        pos = str(entry.get("pos") or "").strip()
        if not word or not pos:
            continue
        key = (normalize_lemma(word, lang), pos)
        any_keys.add(key)
        for sd in entry.get("senses") or []:
            raw = [str(g) for g in (sd.get("glosses") or sd.get("raw_glosses") or [])]
            definition = raw[0].strip() if raw else ""
            tags = [str(t) for t in sd.get("tags", [])]
            if classify(pos, tags, word, definition, lang) is Tier.C:
                visible_keys.add(key)
                break

    # ---- pass 2: the wordnet side, via the importer's own parser ------------
    members_by_synset, ili_by_synset, similar_pairs, stats = parse_lmf(
        lpath, join_marker=args.join_marker
    )

    matched = hidden_only = unmatched = 0
    raw_sizes: list[int] = []
    matched_sizes: list[int] = []
    resolved: dict[str, list[tuple[str, str, bool]]] = {}
    ex_matched: list = []
    ex_hidden: list = []
    ex_unmatched: list = []
    pos_of_unmatched: Counter = Counter()

    for synset_id, members in members_by_synset.items():
        rows = []
        m = 0
        for surface, pos in members:
            norm = normalize_lemma(surface, lang)
            key = (norm, pos)
            ok = key in visible_keys
            rows.append((surface, norm, ok))
            if ok:
                matched += 1
                m += 1
                if len(ex_matched) < cap:
                    ex_matched.append(surface)
            elif key in any_keys:
                hidden_only += 1
                if len(ex_hidden) < cap:
                    ex_hidden.append((surface, pos))
            else:
                unmatched += 1
                pos_of_unmatched[pos] += 1
                if len(ex_unmatched) < cap:
                    ex_unmatched.append((surface, pos))
        resolved[synset_id] = rows
        raw_sizes.append(len(members))
        matched_sizes.append(m)

    total_members = matched + hidden_only + unmatched

    # ---- predicted output volume (mirrors wordnet_lmf.run()) ---------------
    # run(): synonym edges come from synsets with >=2 RESOLVED members (all
    # members, matched or not), each MATCHED member -> every OTHER norm.
    syn_edges: set[tuple[str, str, str]] = set()
    for synset_id, rows in resolved.items():
        if len(rows) < 2:
            continue
        norms = {r[1] for r in rows}
        for _surf, norm, ok in rows:
            if not ok:
                continue
            for other in norms:
                if other != norm:
                    syn_edges.add((norm, "synonym", other))

    near_edges: set[tuple[str, str, str]] = set()
    for a, b in similar_pairs:
        for src, dst in ((a, b), (b, a)):
            targets = {r[1] for r in resolved.get(dst, [])}
            for _surf, norm, ok in resolved.get(src, []):
                if not ok:
                    continue
                for other in targets:
                    if other != norm:
                        near_edges.add((norm, "near_synonym", other))

    memberships: set[tuple[str, str]] = set()
    synsets_with_ili_and_match = 0
    for synset_id, rows in resolved.items():
        ili = ili_by_synset.get(synset_id)
        if not ili:
            continue
        hit = False
        for _surf, norm, ok in rows:
            if ok:
                memberships.add((norm, ili))
                hit = True
        if hit:
            synsets_with_ili_and_match += 1

    multi = sum(1 for s in matched_sizes if s >= 2)

    def pct(n, d):
        return f"{100 * n / d:.2f}%" if d else "n/a"

    print("=" * 72)
    print(f"KAIKKI: {kpath.name}   entries read: {entries}")
    print(f"LMF   : {lpath.name}   lang_code: {lang!r}")
    print("=" * 72)
    print(f"kaikki keys (any tier) ........... {len(any_keys)}")
    print(f"kaikki keys VISIBLE (Tier C) ..... {len(visible_keys)}  "
          f"({pct(len(visible_keys), len(any_keys))})")
    print()
    for k in ("entries", "senses", "synsets", "synsets_indexed_ili",
              "synsets_unindexed_ili", "entries_skipped_lemma_or_pos",
              "similar_relations"):
        print(f"{k:.<33} {stats.get(k, 0)}")
    print()
    print("--- MEMBER MATCH ---")
    print(f"  matched to a VISIBLE sense ..... {matched} / {total_members} "
          f"({pct(matched, total_members)})")
    print(f"  key exists but HIDDEN/dropped .. {hidden_only} "
          f"({pct(hidden_only, total_members)})   <== taxonomy cost")
    print(f"  no key in the Kaikki file ...... {unmatched} "
          f"({pct(unmatched, total_members)})")
    print(f"  synset size (raw) .............. {_hist(raw_sizes)}")
    print(f"  synset size (matched) .......... {_hist(matched_sizes)}")
    print(f"  synsets with >=2 matched ....... {multi} / {len(matched_sizes)} "
          f"({pct(multi, len(matched_sizes))})   <== only these emit edges")
    print()
    print("--- PREDICTED IMPORT VOLUME ---")
    print(f"  synonym edges .................. {len(syn_edges)}")
    print(f"  near_synonym edges ............. {len(near_edges)}")
    print(f"  membership rows ................ {len(memberships)}")
    print(f"  synsets contributing ILI ....... {synsets_with_ili_and_match}")
    print()
    print(f"  matched samples ...... {ex_matched}")
    print(f"  hidden-only samples .. {ex_hidden}")
    print(f"  unmatched samples .... {ex_unmatched}")
    print(f"  unmatched by POS ..... {pos_of_unmatched.most_common(6)}")


if __name__ == "__main__":
    main()