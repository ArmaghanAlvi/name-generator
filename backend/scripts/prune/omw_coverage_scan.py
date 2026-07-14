"""
OMW WN-LMF coverage scan (read-only, no DB) — Stage 1g.

Point it at one extracted OMW wordnet file (WN-LMF XML, e.g. jpn/wn-data.xml
or however the release lays it out). Reports the numbers the findings doc
needs per language:
  * LexicalEntry / Sense / Synset counts (edge-pool size)
  * Synsets carrying an `ili` attribute (cross-language alignment viability —
    ILI is what lets an OMW synset corroborate a Kaikki translation and link
    to the OEWN edge world)
  * SynsetRelation counts by relType (how many are synonym-grade vs topical)
  * Lemma script sample (sanity: right language, right script)

Streams via iterparse; safe on large files. Accepts .xml or .xml.gz.

USAGE (from backend/):
  python3 scripts/prune/omw_coverage_scan.py <path-to-lmf.xml[.gz]> [--examples N]
"""
from __future__ import annotations

import argparse
import gzip
from collections import Counter
from pathlib import Path
from xml.etree.ElementTree import iterparse


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path)
    ap.add_argument("--examples", type=int, default=10)
    args = ap.parse_args()
    path = args.input.expanduser().resolve()

    opener = gzip.open if path.suffix == ".gz" else open

    lexicons: list[tuple[str, str]] = []
    entries = senses = synsets = 0
    synsets_with_ili = 0
    rel_types: Counter = Counter()
    sense_rel_types: Counter = Counter()
    lemma_samples: list[str] = []

    with opener(path, "rb") as fh:
        for event, elem in iterparse(fh, events=("end",)):
            tag = local(elem.tag)
            if tag == "Lexicon":
                lexicons.append((elem.get("id", "?"), elem.get("language", "?")))
                elem.clear()
            elif tag == "LexicalEntry":
                entries += 1
                elem.clear()
            elif tag == "Lemma":
                if len(lemma_samples) < args.examples:
                    wf = elem.get("writtenForm")
                    if wf:
                        lemma_samples.append(wf)
            elif tag == "Sense":
                senses += 1
            elif tag == "Synset":
                synsets += 1
                ili = elem.get("ili")
                if ili and ili not in ("", "in"):
                    synsets_with_ili += 1
                elem.clear()
            elif tag == "SynsetRelation":
                rel_types[elem.get("relType", "?")] += 1
            elif tag == "SenseRelation":
                sense_rel_types[elem.get("relType", "?")] += 1

    def pct(n, d):
        return f"{100 * n / d:.2f}%" if d else "n/a"

    print("=" * 72)
    print(f"FILE: {path}")
    print("=" * 72)
    print(f"lexicons: {lexicons}")
    print(f"lexical entries .................. {entries}")
    print(f"senses ........................... {senses}")
    print(f"synsets .......................... {synsets}")
    print(f"  with ILI ....................... {synsets_with_ili} ({pct(synsets_with_ili, synsets)})")
    print(f"lemma samples: {lemma_samples}")
    print()
    print("--- SynsetRelation types (top 15) ---")
    for t, n in rel_types.most_common(15):
        print(f"  {t:<24} {n}")
    print("--- SenseRelation types (top 15) ---")
    for t, n in sense_rel_types.most_common(15):
        print(f"  {t:<24} {n}")


if __name__ == "__main__":
    main()
