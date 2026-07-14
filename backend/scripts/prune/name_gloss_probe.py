"""
Name-gloss probe (read-only, no DB) — Stage 4's evidence base.

For every `name`-POS sense in a Kaikki file, buckets the gloss
pipeline-derivably:

  CATEGORICAL       gloss is only a name category ("a female given name",
                    "a surname", "a city in ...") — semantically empty for
                    meaning-search; embedding it adds noise.
  CATEGORICAL+MEANING categorical shape BUT carries semantic content
                    ("a female given name ... meaning 'dawn'") — rescue gold.
  DESCRIPTIVE       everything else ("the Roman goddess of the dawn") —
                    semantic content present; likely rescuable.

Also reports:
  * top unmatched gloss PREFIXES among CATEGORICAL-looking glosses that no
    pattern caught (drives pattern refinement from the output itself,
    no second data pass needed);
  * a rule-12 census — how many senses hit the leading-capital backstop,
    split by POS (Stage 4b needs to know how much rule 12 double-catches).

The buckets here are DESCRIPTIVE measurements; the actual Stage-4 separator
is designed FROM these numbers, not implemented by this probe.

USAGE (from backend/):
  python3 scripts/prune/name_gloss_probe.py <file.jsonl[.gz]> [--limit N] [--examples N]
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

from scripts.prune.prune_attribution_probe import classify_attributed  # noqa: E402

_PLACE_WORDS = (
    "city|town|village|hamlet|river|mountain|lake|island|state|province|"
    "country|county|region|district|commune|municipality|borough|suburb|"
    "neighborhood|neighbourhood|census-designated place|unincorporated|"
    "placename|place name|place-name|locality|locale|civil parish|parish|"
    "prefecture|ward|settlement|community|ghost town|local government area|"
    "tribe|clan"
)

CATEGORICAL_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"^an? (?:[a-z-]+ ){0,4}given name\b",
        r"^an? (?:[a-z-]+ ){0,3}surname\b",
        r"^an? (?:[a-z-]+ ){0,2}(?:patronymic|matronymic)\b",
        r"^an? (?:diminutive|pet form|short form|hypocoristic)s?\b",
        rf"^an? (?:[a-z-]+ ){{0,3}}(?:{_PLACE_WORDS})\b",
        r"^an? place (?:in|of)",
        r"^a number of places",
        r"^the name of (?:a|an|the|many|several|various|numerous)\b",
        r"^the capital (?:city )?of",
        r"^an? taxonomic",
        r"^an? (?:genus|family|order|species) (?:of|in)",
        r"^an? (?:roman )?(?:nomen(?: gentile)?|cognomen|praenomen|agnomen)\b",
        r"^an? transliteration of",
        r"^(?:initialism|acronym|abbreviation|partial initialism|clipping) of",
        r"^short for\b",
        r"^the full form of\b",
        r"^the meaning of this",
        r"^(?:nominative|genitive|dative|accusative|ablative|vocative|locative)\b.{0,30}\bof\b",
        r"\((?:a|an|the) (?:country|city|town|capital|state|province|region|"
        r"river|village|prefecture|island|district)\b",
    )
]

MEANING_MARKERS = re.compile(
    r"\bmeaning\b|\bliterally\b|\bequivalent to\b|\bcognate\b", re.IGNORECASE
)


def iter_jsonl(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield orjson.loads(line)


def sample_add(bucket: list, item, cap: int) -> None:
    if len(bucket) < cap:
        bucket.append(item)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--examples", type=int, default=10)
    args = ap.parse_args()
    path = args.input.expanduser().resolve()
    cap = args.examples

    entries = 0
    name_senses = 0
    buckets: Counter = Counter()
    samples: dict[str, list] = {"CATEGORICAL": [], "CATEGORICAL+MEANING": [],
                                "DESCRIPTIVE": []}
    unmatched_prefixes: Counter = Counter()

    rule12_by_pos: Counter = Counter()
    rule12_samples: list = []
    senses_total = 0

    for entry in iter_jsonl(path):
        if args.limit is not None and entries >= args.limit:
            break
        entries += 1
        word = str(entry.get("word") or "").strip()
        pos = str(entry.get("pos") or "").strip()
        if not word or not pos:
            continue

        for sd in entry.get("senses") or []:
            raw_glosses = [str(g) for g in (sd.get("glosses")
                                            or sd.get("raw_glosses") or [])]
            gloss = raw_glosses[0].strip() if raw_glosses else ""
            tags = [str(t) for t in sd.get("tags", [])]
            senses_total += 1

            # rule-12 census (all POS)
            _, rule = classify_attributed(pos, tags, word, gloss)
            if rule == 12:
                rule12_by_pos[pos] += 1
                sample_add(rule12_samples, (word, pos, gloss[:50]), cap)

            if pos != "name" or not gloss:
                continue
            name_senses += 1

            categorical = any(p.search(gloss) for p in CATEGORICAL_PATTERNS)
            has_meaning = bool(MEANING_MARKERS.search(gloss))

            if categorical and has_meaning:
                b = "CATEGORICAL+MEANING"
            elif categorical:
                b = "CATEGORICAL"
            else:
                b = "DESCRIPTIVE"
                # collect prefixes of descriptive glosses that LOOK categorical
                # ("A ..." shapes) so patterns can be refined from this output
                low = gloss.lower()
                if low.startswith(("a ", "an ", "the ")):
                    unmatched_prefixes[" ".join(low.split()[:4])] += 1
            buckets[b] += 1
            sample_add(samples[b], (word, gloss[:70]), cap)

    def pct(n, d):
        return f"{100 * n / d:.2f}%" if d else "n/a"

    print("=" * 72)
    print(f"FILE: {path}   (entries read: {entries})")
    print("=" * 72)
    print(f"name-POS senses .................. {name_senses}")
    for b in ("CATEGORICAL", "CATEGORICAL+MEANING", "DESCRIPTIVE"):
        print(f"  {b:<22} {buckets[b]:>8} ({pct(buckets[b], name_senses)})")
        for w, g in samples[b]:
            print(f"      {w!r}: {g}")
    print()
    print("--- top unmatched 'a/an/the ...' prefixes among DESCRIPTIVE ---")
    print("    (candidates for pattern refinement — review these shapes)")
    for pfx, n in unmatched_prefixes.most_common(15):
        print(f"    {n:>6}  {pfx!r}")
    print()
    print("--- RULE-12 CENSUS (leading-capital backstop, all POS) ---")
    print(f"  senses classified ............. {senses_total}")
    r12_total = sum(rule12_by_pos.values())
    print(f"  rule-12 hits .................. {r12_total} ({pct(r12_total, senses_total)})")
    for p, n in rule12_by_pos.most_common(10):
        print(f"      pos={p:<10} {n}")
    print(f"  samples: {rule12_samples}")


if __name__ == "__main__":
    main()
