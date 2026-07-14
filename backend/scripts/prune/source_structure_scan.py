"""
Source structure scan (read-only, no DB).

Per Kaikki file, verifies/measures what the importer and the multilingual
engine will depend on:
  1. lang_code / lang uniformity (catches a wrong-edition or mixed download).
  2. Field-shape presence rates (word, pos, senses, glosses) — the importer's
     assumptions, validated per language instead of assumed from English.
  3. Synonym coverage: sense-level and entry-level `synonyms` arrays
     (sizes each language's own expansion graph -> pivot-fallback gate).
  4. Translations coverage (--translations-for xx,yy): entry- and sense-level
     `translations` items per target lang_code, and how many carry a `sense`
     hint (root-selection primary-path gate).
  5. Headword character census: per dominant script, how many headwords carry
     combining marks (Mn), digits, or other non-alpha chars — the ground
     truth for the macron/harakat questions.

USAGE (from backend/):
  python3 scripts/prune/source_structure_scan.py <file.jsonl[.gz]> [--limit N]
      [--examples N] [--translations-for la,ru,ja,ar]
"""
from __future__ import annotations

import argparse
import gzip
import unicodedata
from collections import Counter
from pathlib import Path

import orjson

_LEMMA_EXTRA = "-' "


def iter_jsonl(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield orjson.loads(line)


def dominant_script(word: str) -> str:
    for ch in word:
        if ch.isalpha():
            try:
                head = unicodedata.name(ch).split(" ", 1)[0]
            except ValueError:
                continue
            return "CJK" if head == "CJK" else head
    return "NO_ALPHA"


def sample_add(bucket: list, item, cap: int) -> None:
    if len(bucket) < cap:
        bucket.append(item)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path)
    ap.add_argument("--limit", type=int, default=None, help="max entries")
    ap.add_argument("--examples", type=int, default=8)
    ap.add_argument("--translations-for", type=str, default="",
                    help="comma-separated lang codes to count translations for")
    args = ap.parse_args()
    path = args.input.expanduser().resolve()
    cap = args.examples
    tr_targets = [c.strip() for c in args.translations_for.split(",") if c.strip()]

    entries = 0
    lang_codes: Counter = Counter()
    lang_names: Counter = Counter()
    no_word = no_pos = no_senses = 0
    pos_hist: Counter = Counter()

    senses_total = 0
    senses_with_gloss = 0
    senses_with_syn = 0
    syn_refs_sense_level = 0
    entries_with_entry_syn = 0
    syn_refs_entry_level = 0
    entry_syn_with_sense_hint = 0

    entries_with_translations = 0
    tr_items_total = 0
    tr_items_with_sense_hint = 0
    tr_per_target: Counter = Counter()
    senses_with_translations = 0

    # char census, keyed by dominant script
    script_total: Counter = Counter()
    script_with_mn: Counter = Counter()
    script_with_digit: Counter = Counter()
    script_other_nonalpha: Counter = Counter()
    mn_samples: dict[str, list] = {}
    other_samples: dict[str, list] = {}

    for entry in iter_jsonl(path):
        if args.limit is not None and entries >= args.limit:
            break
        entries += 1

        lang_codes[str(entry.get("lang_code") or "MISSING")] += 1
        lang_names[str(entry.get("lang") or "MISSING")] += 1

        word = str(entry.get("word") or "").strip()
        pos = str(entry.get("pos") or "").strip()
        if not word:
            no_word += 1
        if not pos:
            no_pos += 1
        pos_hist[pos or "MISSING"] += 1

        senses = entry.get("senses") or []
        if not senses:
            no_senses += 1

        if word:
            scr = dominant_script(word)
            script_total[scr] += 1
            has_mn = any(unicodedata.category(c) == "Mn" for c in word)
            has_digit = any(c.isdigit() for c in word)
            other = any(
                not (c.isalpha() or c in _LEMMA_EXTRA)
                and unicodedata.category(c) != "Mn"
                and not c.isdigit()
                for c in word
            )
            if has_mn:
                script_with_mn[scr] += 1
                sample_add(mn_samples.setdefault(scr, []), word, cap)
            if has_digit:
                script_with_digit[scr] += 1
            if other:
                script_other_nonalpha[scr] += 1
                sample_add(other_samples.setdefault(scr, []), word, cap)

        for sd in senses:
            senses_total += 1
            if (sd.get("glosses") or sd.get("raw_glosses")):
                senses_with_gloss += 1
            syns = sd.get("synonyms") or []
            if syns:
                senses_with_syn += 1
                syn_refs_sense_level += len(syns)
            if sd.get("translations"):
                senses_with_translations += 1
                for tr in sd.get("translations") or []:
                    tr_items_total += 1
                    code = str(tr.get("code") or tr.get("lang_code") or "")
                    if code in tr_targets:
                        tr_per_target[code] += 1
                    if tr.get("sense"):
                        tr_items_with_sense_hint += 1

        entry_syns = entry.get("synonyms") or []
        if entry_syns:
            entries_with_entry_syn += 1
            syn_refs_entry_level += len(entry_syns)
            entry_syn_with_sense_hint += sum(1 for s in entry_syns if s.get("sense"))

        trs = entry.get("translations") or []
        if trs:
            entries_with_translations += 1
            for tr in trs:
                tr_items_total += 1
                code = str(tr.get("code") or tr.get("lang_code") or "")
                if code in tr_targets:
                    tr_per_target[code] += 1
                if tr.get("sense"):
                    tr_items_with_sense_hint += 1

    def pct(n, d):
        return f"{100 * n / d:.2f}%" if d else "n/a"

    print("=" * 72)
    print(f"FILE: {path}")
    print("=" * 72)
    print(f"entries .......................... {entries}")
    print(f"  missing word ................... {no_word}")
    print(f"  missing pos .................... {no_pos}")
    print(f"  missing/empty senses ........... {no_senses}")
    print()
    print("--- LANG UNIFORMITY ---")
    for code, n in lang_codes.most_common(5):
        print(f"  lang_code {code!r}: {n} ({pct(n, entries)})")
    for name, n in lang_names.most_common(5):
        print(f"  lang      {name!r}: {n} ({pct(n, entries)})")
    print()
    print("--- POS DISTRIBUTION (top 15) ---")
    for p, n in pos_hist.most_common(15):
        print(f"  {p:<14} {n:>9} ({pct(n, entries)})")
    print()
    print("--- SENSES / GLOSSES ---")
    print(f"  senses total ................... {senses_total}")
    print(f"  senses with gloss .............. {senses_with_gloss} ({pct(senses_with_gloss, senses_total)})")
    print()
    print("--- SYNONYM COVERAGE (this language's own graph) ---")
    print(f"  senses with sense-level syns ... {senses_with_syn} ({pct(senses_with_syn, senses_total)})")
    print(f"  sense-level syn refs total ..... {syn_refs_sense_level}")
    print(f"  entries with entry-level syns .. {entries_with_entry_syn} ({pct(entries_with_entry_syn, entries)})")
    print(f"  entry-level syn refs total ..... {syn_refs_entry_level}")
    print(f"    with 'sense' routing hint .... {entry_syn_with_sense_hint} ({pct(entry_syn_with_sense_hint, syn_refs_entry_level)})")
    print()
    print("--- TRANSLATIONS COVERAGE ---")
    print(f"  entries with translations ...... {entries_with_translations} ({pct(entries_with_translations, entries)})")
    print(f"  senses with translations ....... {senses_with_translations}")
    print(f"  translation items total ........ {tr_items_total}")
    print(f"    with 'sense' hint ............ {tr_items_with_sense_hint} ({pct(tr_items_with_sense_hint, tr_items_total)})")
    if tr_targets:
        for code in tr_targets:
            n = tr_per_target.get(code, 0)
            print(f"    -> target {code!r}: {n} items")
    print()
    print("--- HEADWORD CHARACTER CENSUS (by dominant script) ---")
    for scr, n in script_total.most_common():
        mn = script_with_mn.get(scr, 0)
        dg = script_with_digit.get(scr, 0)
        ot = script_other_nonalpha.get(scr, 0)
        print(f"  {scr:<10} total={n:>8}  with-Mn={mn:>7} ({pct(mn, n)})  "
              f"digits={dg:>6}  other-nonalpha={ot:>6}")
    for scr, words in mn_samples.items():
        print(f"  Mn samples [{scr}]: {words}")
    for scr, words in other_samples.items():
        print(f"  other-nonalpha samples [{scr}]: {words}")


if __name__ == "__main__":
    main()
