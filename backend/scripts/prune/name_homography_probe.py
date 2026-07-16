"""
Stage 4 / Step 1 — homography probe v2 (read-only, no DB).

⟲ REVISED — v1 was invalid on two counts, both visible in its own output:
  1. NO TIER FILTER. It compared raw glosses, so Latin's inflection flood
     dominated: 'Zmyrnam' [name] "accusative singular of Zmyrna" matched
     'zmyrnam' [noun] "accusative singular of zmyrna" and scored RELATED.
     Both are form-of -> Tier A -> hard-dropped -> NEVER IN THE DATABASE.
     The probe measured a population the feature cannot see.
  2. ASCII-ONLY TOKENIZER. `[a-z]+` shreds macrons: 'sȳrinx' -> 'rinx',
     'phoenīx' -> 'phoen'. Shrapnel matched shrapnel (the nus/tus/lis/rus
     entries in v1's top-tokens). Both bugs inflated RELATED.
Production was never affected: Tier-A senses aren't in the DB, so the real
join is tier-filtered by construction. Only the measurement was wrong.

THE QUESTION
------------
The shadow join labels a Tier-C word as "also a name" when a Tier-B name-POS
lexeme shares its canonical key. Sharing a key is not sharing a meaning:

    aurora (noun) "dawn, sunrise"  /  Aurora (name) "the goddess of the dawn"
        -> coherent; the name IS the word
    lucius (noun) "a fish, probably the pike"  /  Lucius (name) "a masculine
    praenomen"
        -> coincidence; Lucius is from lux (light), not from the pike

Only pairs that SURVIVE TO THE DATABASE are compared:
    name side   -> classify() is Tier.B  (what the label would read)
    common side -> classify() is Tier.C  (what meaning-search surfaces)

LIMITATION (read the output with this in mind)
----------------------------------------------
Measures GLOSS-ATTESTED relatedness, not etymology. `Felix` really does mean
"lucky", but its gloss is "A cognomen, particularly of later Roman emperors"
-- zero overlap with felix/"happy, lucky, blessed" -> buckets COINCIDENTAL.
No stemming either ("fortune" != "fortunate").
So COINCIDENTAL is an OVER-count. RELATED is a floor, not an estimate.
A high RELATED rate is trustworthy; a low one is ambiguous.

USAGE (from backend/):
  python3 scripts/prune/name_homography_probe.py \
      ~/Personal-Projects/datasets/kaikki/kaikki-latin.jsonl.gz --lang-code la
"""
from __future__ import annotations

import argparse
import gzip
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import orjson

sys.path.insert(0, os.getcwd())

from app.services.prune_taxonomy import Tier, classify  # noqa: E402
from app.utils.text import normalize_lemma  # noqa: E402

# Unicode-aware: letters only, no digits/underscore. Combined with _fold()'s
# mark-stripping, 'sȳrinx' -> 'syrinx' as ONE token instead of 'rinx'.
_TOKEN_RX = re.compile(r"[^\W\d_]+", re.UNICODE)

MIN_TOKEN_LEN = 3

# Function words + name-gloss boilerplate + geography + inflection terminology.
# The inflection block is a BACKSTOP: the tier filter should remove form-of
# senses before they reach here, but v1 proved this is where silent inflation
# hides. Section 4 of the report is the check on whether this list holds.
STOPWORDS: frozenset[str] = frozenset("""
a an the of in on at to from by for with and or but not as
is are was were be been being has have had do does did
this that these those it its his her their our your my one
who whom whose which what where when how why while
also especially chiefly originally particularly usually often sometimes
used using use meaning means called
male female unisex masculine feminine neuter given name names
surname surnames patronymic patronymics
nickname nicknames epithet cognomen praenomen nomen gentile gens clan family
equivalent english transferred derived derivative variant variants
form forms alternative spelling spellings transliteration romanization
diminutive short shortened clipping abbreviation initialism
place places placename placenames city cities town towns village villages
county counties state states country countries region regions
province provinces district districts municipality municipalities
river rivers mountain mountains island islands lake lakes sea ocean
capital located situated northern southern eastern western
north south east west central
ancient modern historical former present
roman greek latin hebrew arabic japanese russian german french spanish
italian irish scottish english dutch hindi sanskrit persian gaelic yiddish
mythology myth god goddess deity divine
number several various many multiple any some other others both
famously known notably including
nominative accusative genitive dative ablative vocative locative
instrumental singular plural dual
perfect imperfect pluperfect active passive indicative subjunctive
imperative infinitive participle supine gerund
first second third person comparative superlative degree positive
inflection inflected declension conjugation letter case
""".split())


def _fold(s: str) -> str:
    """NFD-decompose, drop marks, lowercase. Makes macrons/harakat invisible
    to the tokenizer instead of fragmenting on them."""
    d = unicodedata.normalize("NFD", s)
    return "".join(c for c in d if unicodedata.category(c) != "Mn").lower()


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


def content_tokens(gloss: str, lemma: str) -> set[str]:
    """Content words in a gloss, minus boilerplate and the lemma itself.

    The lemma is discarded because name glosses routinely restate it
    ("Aurora, the goddess of the dawn") -- matching on it would prove only
    that Kaikki repeats the headword.
    """
    toks = {t for t in _TOKEN_RX.findall(_fold(gloss)) if len(t) >= MIN_TOKEN_LEN}
    toks -= STOPWORDS
    toks.discard(_fold(lemma))
    return toks


def match_kind(a: str, b: str) -> str:
    """Why two raw lemmas collided on one canonical key."""
    a_n = unicodedata.normalize("NFC", a)
    b_n = unicodedata.normalize("NFC", b)
    if a_n == b_n:
        return "identical"
    if a_n.casefold() == b_n.casefold():
        return "case_only"
    return "normalization"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path)
    ap.add_argument("--lang-code", type=str, required=True)
    ap.add_argument("--examples", type=int, default=10)
    ap.add_argument("--min-shared", type=int, default=1,
                    help="shared content words required to call a pair RELATED")
    args = ap.parse_args()

    path = args.input.expanduser().resolve()
    lc, cap = args.lang_code, args.examples

    # PASS 1: key -> POS set (cheap superset; no classify yet). Lets PASS 2
    # hold glosses only for keys that could possibly matter.
    pos_by_key: dict[str, set[str]] = {}
    for entry in iter_jsonl(path):
        word = str(entry.get("word") or "").strip()
        pos = str(entry.get("pos") or "").strip().lower()
        if not word or not pos:
            continue
        key = normalize_lemma(word, lc)
        if key:
            pos_by_key.setdefault(key, set()).add(pos)

    shadowed_raw = {
        k for k, ps in pos_by_key.items() if "name" in ps and (ps - {"name"})
    }
    del pos_by_key

    # PASS 2: glosses for shadowed keys, TIER-FILTERED.
    names: dict[str, list[tuple[str, str]]] = defaultdict(list)
    commons: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    dropped_name: Counter = Counter()
    dropped_common: Counter = Counter()

    for entry in iter_jsonl(path):
        word = str(entry.get("word") or "").strip()
        pos = str(entry.get("pos") or "").strip().lower()
        if not word or not pos:
            continue
        key = normalize_lemma(word, lc)
        if key not in shadowed_raw:
            continue
        for sd in entry.get("senses") or []:
            gloss = gloss_of(sd)
            if len(gloss) < 3:
                continue
            tags = [str(t) for t in sd.get("tags", [])]
            tier = classify(pos, tags, word, gloss)
            if pos == "name":
                # Tier B only: what the label would actually read. Tier A
                # (form-of / alt-of) never reaches the DB; provisional-alt
                # rows are hidden but say "alternative form of X" -- not a
                # name meaning.
                if tier is not Tier.B:
                    dropped_name[tier.value] += 1
                    continue
                names[key].append((word, gloss))
            else:
                # Tier C only: what meaning-search actually surfaces.
                if tier is not Tier.C:
                    dropped_common[tier.value] += 1
                    continue
                commons[key].append((word, pos, gloss))

    # PASS 3: best-overlapping common sense per name sense.
    n_related = n_coincidental = 0
    kinds: Counter = Counter()
    kind_by_bucket: Counter = Counter()
    shadow_pos: Counter = Counter()
    shared_tokens: Counter = Counter()
    effective_keys = 0
    ex_rel: list = []
    ex_coin: list = []
    ex_norm: list = []

    for key in shadowed_raw:
        n_list = names.get(key) or []
        c_list = commons.get(key) or []
        if not n_list or not c_list:
            continue
        effective_keys += 1

        for nlemma, ngloss in n_list:
            ntok = content_tokens(ngloss, nlemma)
            best_n, best = 0, None
            for clemma, cpos, cgloss in c_list:
                shared = ntok & content_tokens(cgloss, clemma)
                if len(shared) > best_n or best is None:
                    best_n, best = len(shared), (clemma, cpos, cgloss, shared)

            clemma, cpos, cgloss, shared = best # type: ignore
            kind = match_kind(nlemma, clemma)
            kinds[kind] += 1
            shadow_pos[cpos] += 1

            if best_n >= args.min_shared:
                n_related += 1
                kind_by_bucket[("RELATED", kind)] += 1
                shared_tokens.update(shared)
                if len(ex_rel) < cap:
                    ex_rel.append((nlemma, ngloss[:52], clemma, cpos,
                                   cgloss[:38], sorted(shared)[:4]))
            else:
                n_coincidental += 1
                kind_by_bucket[("COINCIDENTAL", kind)] += 1
                if len(ex_coin) < cap:
                    ex_coin.append((nlemma, ngloss[:52], clemma, cpos, cgloss[:38]))

            if kind == "normalization" and len(ex_norm) < cap:
                ex_norm.append((nlemma, clemma, cpos, cgloss[:44]))

    total = n_related + n_coincidental

    def pct(n, d):
        return f"{100 * n / d:.2f}%" if d else "n/a"

    print("=" * 72)
    print(f"FILE: {path}   lang_code: {lc!r}   min-shared: {args.min_shared}")
    print("=" * 72)
    print(f"shadowed keys (POS only, pre-tier) ...... {len(shadowed_raw)}")
    print(f"EFFECTIVE keys (both sides survive tier)  {effective_keys}")
    print(f"name senses dropped by tier ............. "
          f"{dict(dropped_name)}  (A=purged, C=n/a for name POS)")
    print(f"common senses dropped by tier ........... {dict(dropped_common)}")
    print(f"comparable name senses .................. {total}")
    if total == 0:
        print("\nNothing comparable survives the tier filter for this language.")
        return

    print()
    print("--- 1. RELATED vs COINCIDENTAL (DB-resident pairs only) ---")
    print(f"  RELATED (gloss overlap) ....... {n_related} ({pct(n_related, total)})")
    print(f"  COINCIDENTAL (no overlap) ..... {n_coincidental} ({pct(n_coincidental, total)})")
    print("  NOTE: COINCIDENTAL is an over-count — see the module docstring.")

    print()
    print("--- 2. KEY-MATCH KIND (why the lemmas collided) ---")
    for k in ("identical", "case_only", "normalization"):
        n = kinds[k]
        flag = "  <== our normalization merged these" if k == "normalization" and n else ""
        print(f"  {k:<14} {n:>7} ({pct(n, total)}){flag}")
    print()
    print("  cross-tab:")
    for bucket in ("RELATED", "COINCIDENTAL"):
        for k in ("identical", "case_only", "normalization"):
            n = kind_by_bucket[(bucket, k)]
            if n:
                print(f"      {bucket:<12} x {k:<14} {n:>7}")

    print()
    print("--- 3. SHADOWING COMMON-WORD POS ---")
    for p, n in shadow_pos.most_common(8):
        print(f"  {p:<12} {n:>7} ({pct(n, total)})")

    print()
    print("--- 4. TOP SHARED TOKENS AMONG RELATED (stopword self-check) ---")
    print("    (inflection terms here => STOPWORDS is leaking; v1 died of this)")
    for t, n in shared_tokens.most_common(15):
        print(f"    {n:>6}  {t}")

    print()
    print("--- samples: RELATED ---")
    for nl, ng, cl, cp, cg, sh in ex_rel:
        print(f"  {nl!r} [name] {ng}")
        print(f"      <-> {cl!r} [{cp}] {cg}   shared: {sh}")
    print()
    print("--- samples: COINCIDENTAL ---")
    for nl, ng, cl, cp, cg in ex_coin:
        print(f"  {nl!r} [name] {ng}")
        print(f"      <-> {cl!r} [{cp}] {cg}")
    if ex_norm:
        print()
        print("--- samples: NORMALIZATION-COLLAPSED (raw lemmas differ beyond case) ---")
        for nl, cl, cp, cg in ex_norm:
            print(f"  name {nl!r}  <->  {cl!r} [{cp}] {cg}")


if __name__ == "__main__":
    main()