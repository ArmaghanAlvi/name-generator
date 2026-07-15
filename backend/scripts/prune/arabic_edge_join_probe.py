"""
Arabic edge-join probe (read-only, no DB).

Measures how well synonym REFERENCES inside a Kaikki file resolve to
HEADWORDS in the same file, under three lemma-normalization policies:

  P1 current    : normalize_text as-is (NFKC + casefold)          [status quo]
  P2 +mn_strip  : P1 then drop non-spacing marks (harakat)        [Stage 2c]
  P3 +fold      : P2 then Arabic orthographic folding             [Stage 3a gate]
                  (alef variants -> ا, ى -> ي, ة -> ه, drop tatweel)

The P2->P3 delta IS the Stage-3 decision: if P2 already joins ~everything,
folding is dead weight; if P3 meaningfully beats P2, folding earns its
complexity. Zero review either way.

Script-generic (works on any language file), but the folding step only
touches Arabic-block codepoints, so on non-Arabic files P3 == P2.

USAGE (from backend/):
  python3 scripts/prune/arabic_edge_join_probe.py <file.jsonl[.gz]> [--limit N] [--examples N]
"""
from __future__ import annotations

import argparse
import gzip
import os
import sys
import unicodedata
from pathlib import Path

import orjson

sys.path.insert(0, os.getcwd())

from app.utils.text import normalize_text  # noqa: E402
from app.utils.text import normalize_lemma as canonical

_ALEF_VARIANTS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
                                "ى": "ي", "ة": "ه"})
_TATWEEL = "\u0640"


def p1(s: str) -> str:
    return normalize_text(s)


def p2(s: str) -> str:
    return "".join(c for c in p1(s) if unicodedata.category(c) != "Mn")


def p3(s: str) -> str:
    return p2(s).translate(_ALEF_VARIANTS).replace(_TATWEEL, "")


def p4(s: str) -> str:
    # Full diacritic fold: NFD-decompose (splits precomposed chars like
    # ē/é/ё into base + Mn), strip ALL Mn, NFC-recompose, then Arabic fold.
    # This is what P2 cannot do: P2 only strips marks that ARRIVE combining;
    # P4 also folds marks baked into precomposed codepoints.
    d = unicodedata.normalize("NFD", p1(s))
    stripped = "".join(c for c in d if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", stripped).translate(_ALEF_VARIANTS).replace(_TATWEEL, "")


POLICIES = (("P1 current", p1), ("P2 +mn_strip", p2),
            ("P3 +fold", p3), ("P4 +full_fold", p4))


def iter_jsonl(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield orjson.loads(line)


def syn_word(item) -> str:
    if isinstance(item, dict):
        return str(item.get("word") or "").strip()
    if isinstance(item, str):
        return item.strip()
    return ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--examples", type=int, default=10)
    ap.add_argument("--lang-code", type=str, default=None,
                    help="pass the file's lang code to test the CANONICAL key")
    args = ap.parse_args()
    path = args.input.expanduser().resolve()
    cap = args.examples

    # Built HERE, not at module level, so the lambda closes over parsed args.
    # P5 is the SHIPPED key: it must reproduce P2 for ar/ru, P4 for la, P1 for en.
    policies = list(POLICIES) + [
        ("P5 canonical", lambda s: canonical(s, args.lang_code)),
    ]

    # Pass 1: headword sets under each policy.
    headsets: dict[str, set] = {name: set() for name, _ in policies}
    entries = 0
    for entry in iter_jsonl(path):
        if args.limit is not None and entries >= args.limit:
            break
        entries += 1
        word = str(entry.get("word") or "").strip()
        if not word:
            continue
        for name, fn in policies:
            headsets[name].add(fn(word))

    # Pass 2: synonym references, joined under each policy.
    refs_total = 0
    refs_single = 0
    joined: dict[str, int] = {name: 0 for name, _ in policies}
    joined_single: dict[str, int] = {name: 0 for name, _ in policies}
    unresolved_samples: list = []
    fold_only_samples: list = []

    seen = 0
    for entry in iter_jsonl(path):
        if args.limit is not None and seen >= args.limit:
            break
        seen += 1
        refs = []
        for sd in entry.get("senses") or []:
            refs.extend(syn_word(s) for s in sd.get("synonyms") or [])
        refs.extend(syn_word(s) for s in entry.get("synonyms") or [])
        for ref in refs:
            if not ref:
                continue
            refs_total += 1
            single = " " not in ref
            if single:
                refs_single += 1
            hit = {}
            for name, fn in policies:
                ok = fn(ref) in headsets[name]
                hit[name] = ok
                if ok:
                    joined[name] += 1
                    if single:
                        joined_single[name] += 1
            if hit["P4 +full_fold"] and not hit["P2 +mn_strip"]:
                if len(fold_only_samples) < cap:
                    fold_only_samples.append(ref)
            if not hit["P4 +full_fold"] and single:
                if len(unresolved_samples) < cap:
                    unresolved_samples.append(ref)

    def pct(n, d):
        return f"{100 * n / d:.2f}%" if d else "n/a"

    print("=" * 72)
    print(f"FILE: {path}   (entries read: {entries})   lang_code: {args.lang_code!r}")
    print("=" * 72)
    print(f"synonym refs total ............... {refs_total}")
    print(f"  single-word refs ............... {refs_single} ({pct(refs_single, refs_total)})")
    print()
    print("--- JOIN RATE BY POLICY ---")
    for name, _ in policies:
        print(f"  {name:<14} all: {joined[name]:>8} ({pct(joined[name], refs_total)})   "
              f"single-word: {joined_single[name]:>8} ({pct(joined_single[name], refs_single)})")
    print()
    print(f"joined by P4 but NOT P2 (full fold's unique wins), samples: {fold_only_samples}")
    print(f"single-word refs unresolved even under P4, samples: {unresolved_samples}")

if __name__ == "__main__":
    main()