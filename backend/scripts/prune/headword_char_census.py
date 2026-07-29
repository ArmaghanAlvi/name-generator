"""B2 — headword character-category census. Read-only, stdlib+orjson only.

WHY: source_structure_scan.py reports Mn on headwords but not Mc (Devanagari
matras) or Cf (ZWNJ/ZWJ). B2's question is "where does the decoration live —
headwords or references?", and for hi/sa (Mc) and fa (Cf) the shipped scan
cannot answer it. This census does, per category, with the top decorating
codepoints named so a surprising number is immediately inspectable.
"""
import argparse
import gzip
import sys
import unicodedata
from collections import Counter

import orjson

WATCH = ("Mn", "Mc", "Cf")


def census(path: str, lang_code: str | None, limit: int | None) -> None:
    total = 0
    hits: Counter = Counter()
    examples: dict[str, list[str]] = {c: [] for c in WATCH}
    codepoints: Counter = Counter()

    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rb") as fh:
        for line in fh:
            if limit and total >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                entry = orjson.loads(line)
            except orjson.JSONDecodeError:
                continue
            if lang_code and entry.get("lang_code") != lang_code:
                continue
            word = entry.get("word")
            if not word:
                continue
            total += 1
            cats = {unicodedata.category(ch) for ch in word}
            for c in WATCH:
                if c in cats:
                    hits[c] += 1
                    if len(examples[c]) < 8:
                        examples[c].append(word)
            for ch in word:
                if unicodedata.category(ch) in WATCH:
                    codepoints[f"U+{ord(ch):04X} {unicodedata.name(ch, '?')}"] += 1

    print(f"file: {path}")
    print(f"headwords counted: {total}")
    for c in WATCH:
        pct = (hits[c] / total * 100) if total else 0.0
        print(f"  with {c}: {hits[c]:,} ({pct:.2f}%)  e.g. {examples[c]}")
    print("\ntop decorating codepoints:")
    for cp, n in codepoints.most_common(15):
        print(f"  {n:>8,}  {cp}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path")
    ap.add_argument("--lang-code", default=None)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    census(a.path, a.lang_code, a.limit)
    sys.exit(0)