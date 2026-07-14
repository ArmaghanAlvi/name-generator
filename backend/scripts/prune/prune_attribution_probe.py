"""
Rule-attribution + counterfactual pruning probe (multilingual import diagnostic).

WHY THIS EXISTS
---------------
`classify_only_stats.py` tells you the A/B/C split but not *which rule* fired,
so it can't distinguish "rule 7 dropped junk (Det., S.F.X.)" from "rule 7 ate a
real word because of a diacritic". Under the zero-review constraint that
difference is the whole game for Latin (combining macrons) and Arabic (harakat).

This probe answers three questions per Kaikki file, with ZERO hand review:
  1. Where does the mass go?  -> first-match rule histogram (rules 1..13).
  2. Is rule 7 (the isalpha gate) eating real words? -> rule-7 deep dive:
     of the senses rule 7 drops, how many become classifiable again under a
     lemma fix, and where they land (C vs B) vs. stay A (genuine junk).
  3. What would each candidate fix rescue, and does it regress anything?
     -> counterfactual cross-tab for two lemma transforms:
        * nfc        : NFC-normalize the lemma (the Latin combining-macron fix)
        * nfc_strip  : NFC then drop remaining Mn marks (adds the Arabic harakat
                       fix; NFC-first means Latin macrons COMPOSE and survive,
                       only non-composing marks like harakat are stripped)

It imports the REAL `classify` and the REAL rule constants, and self-checks its
attributed re-implementation against `classify` on every sense, so it cannot
silently drift from the taxonomy it's measuring.

Extraction mirrors kaikki_english.py / classify_only_stats.py exactly (same
word/pos skip, same gloss+tag extraction), so the numbers line up with what the
importer would actually do.

USAGE (from backend/):
  python3 scripts/prune/prune_attribution_probe.py ~/Personal-Projects/datasets/kaikki/kaikki-Latin.jsonl.gz
  python3 scripts/prune/prune_attribution_probe.py <file> --limit 200000 --examples 12
"""
from __future__ import annotations

import argparse
import gzip
import os
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import orjson

sys.path.insert(0, os.getcwd())

from app.services.prune_taxonomy import (  # noqa: E402
    Tier,
    classify,
    sole_alt_trigger,
    TIER_A_POS,
    TIER_A_TAGS,
    TIER_B_POS,
    TIER_B_TAGS,
    _ALLOWED_LEMMA_CHARS,
    _is_western_single_letter,
)

# Execution-order rule indices (NOT the comment numbers in prune_taxonomy.py,
# which are off by one in places). Rules 1-8 -> Tier A, 9-12 -> Tier B, 13 -> C.
RULE_NAMES: dict[int, str] = {
    1: "definition too short (<3 chars)",
    2: "empty lemma",
    3: "Tier-A POS (function word / affix / glyph / phrase / intj)",
    4: "Tier-A tag (form-of, alt-of, abbrev, acronym, vulgar, ...)",
    5: "digit in lemma",
    6: "hyphen-edge affix (-x / x-)",
    7: "non-alpha char in lemma  [THE isalpha GATE]",
    8: "lone Latin/Cyrillic/Greek letter",
    9: "Tier-B POS (name / num)",
    10: "Tier-B tag (slang, obsolete, archaic, dialectal, plural-only, ...)",
    11: "multiword (space in lemma)",
    12: "leading-capital backstop",
    13: "Tier C  -> KEPT & EMBEDDED",
}
TIER_A_RULES = frozenset(range(1, 9))
ISALPHA_RULE = 7


def classify_attributed(pos: str, tags, lemma: str, definition: str) -> tuple[Tier, int]:
    """Faithful mirror of classify() that also returns which rule fired.

    Kept in lockstep with the real classify() by (a) importing its constants and
    helper, and (b) the per-sense assert in the main loop. Only a change to the
    conditional *structure* could desync this, and the assert catches that.
    """
    pos_n = (pos or "").strip().lower()
    tag_set = {str(t).strip().lower() for t in (tags or [])}
    lem = (lemma or "").strip()
    defn = (definition or "").strip()

    if len(defn) < 3:
        return Tier.A, 1
    if not lem:
        return Tier.A, 2
    if pos_n in TIER_A_POS:
        return Tier.A, 3
    if tag_set & TIER_A_TAGS:
        return Tier.A, 4
    if any(ch.isdigit() for ch in lem):
        return Tier.A, 5
    if lem.startswith("-") or lem.endswith("-"):
        return Tier.A, 6
    if not all(ch.isalpha() or ch in _ALLOWED_LEMMA_CHARS for ch in lem):
        return Tier.A, 7
    if _is_western_single_letter(lem):
        return Tier.A, 8
    if pos_n in TIER_B_POS:
        return Tier.B, 9
    if tag_set & TIER_B_TAGS:
        return Tier.B, 10
    if " " in lem:
        return Tier.B, 11
    if lem[:1].isupper() and not lem.isupper():
        return Tier.B, 12
    return Tier.C, 13


# --- lemma transforms (candidate fixes) ------------------------------------
def t_nfc(lem: str) -> str:
    return unicodedata.normalize("NFC", lem)


def t_nfc_strip(lem: str) -> str:
    # NFC first so composing marks (Latin combining macron) fold into a single
    # letter and SURVIVE; only leftover nonspacing marks (Arabic harakat, which
    # do not compose) are dropped.
    return "".join(
        c for c in unicodedata.normalize("NFC", lem)
        if unicodedata.category(c) != "Mn"
    )


TRANSFORMS = {"nfc": t_nfc, "nfc_strip": t_nfc_strip}


def dominant_script(lem: str) -> str:
    for ch in lem:
        if ch.isalpha():
            try:
                name = unicodedata.name(ch)
            except ValueError:
                continue
            head = name.split(" ", 1)[0]
            if head in ("CJK",):
                return "CJK"
            return head
    # no alpha char -> report the first non-space char's script-ish bucket
    for ch in lem:
        if ch.strip():
            try:
                return unicodedata.name(ch).split(" ", 1)[0]
            except ValueError:
                return "UNNAMED"
    return "EMPTY"


def iter_jsonl(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield orjson.loads(line)


def sample_add(bucket: list, item, cap: int) -> None:
    if len(bucket) < cap:
        bucket.append(item)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path, help="Kaikki .jsonl or .jsonl.gz")
    ap.add_argument("--limit", type=int, default=None, help="max ENTRIES to read")
    ap.add_argument("--examples", type=int, default=10, help="sample lemmas per bucket")
    args = ap.parse_args()

    path = args.input.expanduser().resolve()
    cap = args.examples

    entries_seen = 0
    entries_skipped_no_word_pos = 0
    entries_skipped_no_senses = 0
    senses_total = 0
    provisional_alt = 0
    drift_mismatches = 0
    drift_samples: list = []

    rule_hist: Counter = Counter()          # first-match rule -> count
    tier_hist: Counter = Counter()          # Tier -> count

    # rule-7 deep dive
    r7_total = 0
    r7_rescued_nfc = 0                       # not-A after nfc
    r7_rescued_nfc_strip = 0                 # not-A after nfc_strip
    r7_to_C = 0                              # nfc_strip lands in C
    r7_to_B = 0                              # nfc_strip lands in B
    r7_still_A = 0                           # genuine junk
    r7_script: Counter = Counter()
    r7_ex_to_C: list = []
    r7_ex_to_B: list = []
    r7_ex_still_A: list = []

    # counterfactual cross-tabs: transform -> {(from_tier, to_tier): count}
    xtab: dict[str, Counter] = {name: Counter() for name in TRANSFORMS}
    regressions: dict[str, list] = {name: [] for name in TRANSFORMS}

    for entry in iter_jsonl(path):
        if args.limit is not None and entries_seen >= args.limit:
            break
        entries_seen += 1

        word = str(entry.get("word") or "").strip()
        pos = str(entry.get("pos") or "").strip()
        if not word or not pos:
            entries_skipped_no_word_pos += 1
            continue
        senses = entry.get("senses") or []
        if not senses:
            entries_skipped_no_senses += 1
            continue

        for sense_data in senses:
            raw_glosses = [
                str(g) for g in (
                    sense_data.get("glosses") or sense_data.get("raw_glosses") or []
                )
            ]
            definition = raw_glosses[0].strip() if raw_glosses else ""
            tags = [str(t) for t in sense_data.get("tags", [])]

            senses_total += 1

            real_tier = classify(pos, tags, word, definition)
            attr_tier, rule = classify_attributed(pos, tags, word, definition)
            if attr_tier is not real_tier:
                drift_mismatches += 1
                sample_add(drift_samples, (word, pos, real_tier.value, attr_tier.value, rule), cap)

            tier_hist[real_tier] += 1
            rule_hist[rule] += 1
            if real_tier is Tier.A and sole_alt_trigger(pos, tags, word, definition):
                provisional_alt += 1

            # counterfactual cross-tabs (only compute when a transform changes the lemma)
            for name, fn in TRANSFORMS.items():
                new_lem = fn(word)
                if new_lem == word:
                    xtab[name][(real_tier.value, real_tier.value)] += 1
                    continue
                new_tier = classify(pos, tags, new_lem, definition)
                xtab[name][(real_tier.value, new_tier.value)] += 1
                # regression = something LEFT C, or a kept row became A
                if real_tier is Tier.C and new_tier is not Tier.C:
                    sample_add(regressions[name], (word, new_lem, real_tier.value, new_tier.value), cap)
                elif real_tier is Tier.B and new_tier is Tier.A:
                    sample_add(regressions[name], (word, new_lem, real_tier.value, new_tier.value), cap)

            # rule-7 deep dive
            if rule == ISALPHA_RULE:
                r7_total += 1
                r7_script[dominant_script(word)] += 1
                nfc_tier = classify(pos, tags, t_nfc(word), definition)
                strip_tier = classify(pos, tags, t_nfc_strip(word), definition)
                if nfc_tier is not Tier.A:
                    r7_rescued_nfc += 1
                if strip_tier is not Tier.A:
                    r7_rescued_nfc_strip += 1
                    if strip_tier is Tier.C:
                        r7_to_C += 1
                        sample_add(r7_ex_to_C, (word, t_nfc_strip(word), definition[:50]), cap)
                    else:
                        r7_to_B += 1
                        sample_add(r7_ex_to_B, (word, t_nfc_strip(word), pos), cap)
                else:
                    r7_still_A += 1
                    sample_add(r7_ex_still_A, (word, definition[:50]), cap)

    # ---------------- report ----------------
    def pct(n: int, d: int) -> str:
        return f"{100 * n / d:.2f}%" if d else "n/a"

    print("=" * 72)
    print(f"FILE: {path}")
    print("=" * 72)
    print(f"entries seen ...................... {entries_seen}")
    print(f"  skipped (no word or pos) ....... {entries_skipped_no_word_pos}")
    print(f"  skipped (no senses) ............ {entries_skipped_no_senses}")
    print(f"senses classified ................ {senses_total}")
    if senses_total == 0:
        print("\nNo senses classified — check the file path / format.")
        return

    print()
    print("--- SELF-CHECK (attributed vs real classify) ---")
    if drift_mismatches == 0:
        print("OK: attributed rules match classify() on every sense.")
    else:
        print(f"!! DRIFT: {drift_mismatches} mismatches — probe is out of sync with taxonomy!")
        for w, p, rt, at, rl in drift_samples:
            print(f"    {w!r} pos={p} real={rt} attributed={at}(rule {rl})")

    print()
    print("--- TIER SPLIT (real classify) ---")
    for t in Tier:
        n = tier_hist[t]
        print(f"  {t.value}: {n:>10}  ({pct(n, senses_total)})")
    print(f"  provisional-alt (subset of A, kept hidden): {provisional_alt} ({pct(provisional_alt, senses_total)})")

    print()
    print("--- FIRST-MATCH RULE HISTOGRAM ---")
    for r in range(1, 14):
        n = rule_hist.get(r, 0)
        tier = "A" if r in TIER_A_RULES else ("C" if r == 13 else "B")
        star = "  <==" if r == ISALPHA_RULE and n else ""
        print(f"  rule {r:>2} [{tier}] {n:>10}  ({pct(n, senses_total)})  {RULE_NAMES[r]}{star}")

    print()
    print("--- RULE 7 DEEP DIVE (the isalpha gate) ---")
    print(f"  rule-7 drops total ............... {r7_total}  ({pct(r7_total, senses_total)} of senses)")
    if r7_total:
        print(f"  rescued by nfc alone ............. {r7_rescued_nfc}  ({pct(r7_rescued_nfc, r7_total)})")
        print(f"  rescued by nfc_strip ............. {r7_rescued_nfc_strip}  ({pct(r7_rescued_nfc_strip, r7_total)})")
        print(f"     -> would land in C (embedded) . {r7_to_C}  ({pct(r7_to_C, r7_total)})")
        print(f"     -> would land in B (hidden) ... {r7_to_B}  ({pct(r7_to_B, r7_total)})")
        print(f"  still A after nfc_strip (junk) ... {r7_still_A}  ({pct(r7_still_A, r7_total)})")
        print("  rule-7 drops by script:")
        for scr, n in r7_script.most_common():
            print(f"      {scr:<12} {n:>8}  ({pct(n, r7_total)})")
        print(f"  sample rule-7 -> C after fix (real words lost today):")
        for w, fixed, d in r7_ex_to_C:
            print(f"      {w!r} -> {fixed!r}   def: {d}")
        print(f"  sample rule-7 -> B after fix:")
        for w, fixed, p in r7_ex_to_B:
            print(f"      {w!r} -> {fixed!r}   pos={p}")
        print(f"  sample rule-7 still-A (genuine junk, correctly dropped):")
        for w, d in r7_ex_still_A:
            print(f"      {w!r}   def: {d}")

    print()
    print("--- COUNTERFACTUAL CROSS-TABS (transitions that CHANGE tier) ---")
    for name in TRANSFORMS:
        print(f"  [{name}]")
        changed = {k: v for k, v in xtab[name].items() if k[0] != k[1]}
        if not changed:
            print("      (no tier changes)")
        for (frm, to), n in sorted(changed.items()):
            flag = ""
            if frm == "A" and to == "C":
                flag = "  <== rescued to EMBEDDED"
            elif frm == "A" and to == "B":
                flag = "  <== rescued to hidden"
            elif frm == "C":
                flag = "  <== !! REGRESSION (lost an embed candidate)"
            print(f"      {frm} -> {to}: {n}{flag}")
        if regressions[name]:
            print("      regression samples:")
            for w, fixed, frm, to in regressions[name]:
                print(f"        {w!r} -> {fixed!r}  ({frm}->{to})")


if __name__ == "__main__":
    main()
