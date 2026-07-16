"""
Stage 4 / Step 1 probe — the two measurements that decide Stage 4's shape.
Read-only, no DB. Run per language file from backend/.

(1a) MEANING-SHAPE SPLIT
     name_gloss_probe's CATEGORICAL+MEANING bucket conflates two things with
     completely different product value:
       meaning "X"              -> genuine semantic content  (شكرية = "thankful")
       equivalent to English X  -> cross-language NAME link  (Leon = Leon)
     Only the first is what Stage 4 rescues. The second is root-selection
     evidence for the established-names feature (MULTILINGUAL_EXPANSION_MODEL).

(1b) SHADOW CENSUS
     For every name-POS sense: does a NON-name POS entry with the same
     canonical lemma exist in the same file? If yes, that meaning is ALREADY
     reachable through Tier C -- Latin `aurora` (noun, "dawn") already embeds,
     so rescuing name-POS `Aurora` ("the Roman goddess of the dawn") adds a
     LABEL, not a search path. This decides whether Stage 4 is a retrieval
     feature or a display feature.

USAGE (from backend/):
  python3 scripts/prune/name_rescue_probe.py \
      ~/Personal-Projects/datasets/kaikki/kaikki-latin.jsonl.gz --lang-code la
"""
from __future__ import annotations

import argparse
import gzip
import os
import re
import sys
from collections import Counter
from pathlib import Path

import orjson

sys.path.insert(0, os.getcwd())

from app.utils.text import normalize_lemma  # noqa: E402

# Meaning-declaration shapes, checked in order; first match wins.
# Derived from the real CATEGORICAL+MEANING samples, not invented.
MEANING_PATTERNS = [
    ("meaning_quoted", re.compile(r'\bmeaning\s+["\u201c\u2018\']', re.I)),
    ("equiv_english", re.compile(r'\bequivalent to English\b', re.I)),
]


def iter_jsonl(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield orjson.loads(line)


def gloss_of(sd: dict) -> str:
    g = sd.get("glosses") or sd.get("raw_glosses") or []
    return str(g[0]).strip() if g else ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path)
    ap.add_argument("--lang-code", type=str, required=True)
    ap.add_argument("--examples", type=int, default=12)
    args = ap.parse_args()

    path = args.input.expanduser().resolve()
    lc, cap = args.lang_code, args.examples

    # PASS 1: canonical lemma -> set of POS present in this file.
    pos_by_lemma: dict[str, set[str]] = {}
    for entry in iter_jsonl(path):
        word = str(entry.get("word") or "").strip()
        pos = str(entry.get("pos") or "").strip().lower()
        if not word or not pos:
            continue
        key = normalize_lemma(word, lc)
        if key:
            pos_by_lemma.setdefault(key, set()).add(pos)

    # PASS 2: name-POS senses.
    name_senses = 0
    shape: Counter = Counter()
    shadow: Counter = Counter()          # (shape, is_shadowed) -> n
    ex: dict[str, list] = {}
    unmatched_lead: Counter = Counter()

    for entry in iter_jsonl(path):
        word = str(entry.get("word") or "").strip()
        pos = str(entry.get("pos") or "").strip().lower()
        if not word or pos != "name":
            continue
        key = normalize_lemma(word, lc)
        others = pos_by_lemma.get(key, set()) - {"name"}
        is_shadowed = bool(others)

        for sd in entry.get("senses") or []:
            gloss = gloss_of(sd)
            if len(gloss) < 3:
                continue
            name_senses += 1

            matched = "none"
            for label, rx in MEANING_PATTERNS:
                if rx.search(gloss):
                    matched = label
                    break
            shape[matched] += 1
            shadow[(matched, is_shadowed)] += 1
            ex.setdefault(matched, [])
            if len(ex[matched]) < cap:
                ex[matched].append((word, gloss[:70], sorted(others)[:3]))
            if matched == "none":
                unmatched_lead[" ".join(gloss.lower().split()[:4])] += 1

    def pct(n, d):
        return f"{100 * n / d:.2f}%" if d else "n/a"

    print("=" * 72)
    print(f"FILE: {path}   lang_code: {lc!r}")
    print("=" * 72)
    print(f"name-POS senses (gloss >= 3 chars) ...... {name_senses}")
    print()
    print("--- 1a. MEANING-SHAPE SPLIT ---")
    for label in [l for l, _ in MEANING_PATTERNS] + ["none"]:
        n = shape[label]
        sh = shadow[(label, True)]
        print(f"  {label:<16} {n:>7} ({pct(n, name_senses)})"
              f"   of which shadowed: {sh} ({pct(sh, n)})")
    print()
    for label, _ in MEANING_PATTERNS:
        print(f"  samples [{label}]:")
        for w, g, o in ex.get(label, []):
            print(f"      {w!r}: {g}   [other POS: {o}]")
        print()
    print("--- 1b. SHADOW CENSUS (all name-POS senses) ---")
    tot_sh = sum(v for (_m, s), v in shadow.items() if s)
    print(f"  shadowed by a non-name POS of same lemma . {tot_sh} ({pct(tot_sh, name_senses)})")
    print(f"  unshadowed (name-only lemma) ............. {name_senses - tot_sh}")
    print()
    print("--- unmatched gloss leads (pattern refinement candidates) ---")
    for lead, n in unmatched_lead.most_common(15):
        print(f"    {n:>6}  {lead!r}")


if __name__ == "__main__":
    main()