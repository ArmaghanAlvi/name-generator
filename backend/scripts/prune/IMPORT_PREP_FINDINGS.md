# IMPORT_PREP_FINDINGS.md
Stage 1 — Source Acquisition & Diagnostic Sweep: results and decision gates
Status: COMPLETE (all 10 gates closed) · closes on commit
Companion docs: MULTILINGUAL_EXPANSION_MODEL.md, EXPANSION_FEATURE_COMPLETE_RECORD.md
Probes (all in backend/scripts/prune/, all read-only, all self-checked against real classify):
  prune_attribution_probe.py · source_structure_scan.py · arabic_edge_join_probe.py
  name_gloss_probe.py · omw_coverage_scan.py

## 0. Goal & outcome
Verify the pipeline is safe for Latin, Russian, Japanese, Arabic imports without any
manual data review. Outcome: safe to proceed, conditional on the Stage 2/3 fixes recorded
below. The classify gate needs no rescue work (headwords are clean everywhere); the real
work is in the normalized JOIN KEY and a small taxonomy addition. Meaningful proper nouns
are rescuable by positive selection. Wordnet supplementation is viable for ja/ar, absent
for ru/la.

## 1. Decision gates

| #  | Gate | Verdict | Key evidence |
|----|------|---------|--------------|
| 1  | NFC fix load-bearing? | **No** — apply as free insurance only | 0 nfc-only rescues in all 5 files |
| 2  | Harakat rescue at CLASSIFY layer? | **Not needed** ⟲REVISED | AR rule-7 = 14 senses (headwords bare) |
| 3  | Strip Mn in normalized JOIN KEY? | **Required + safe** | AR join 0.68→81%, RU 11→81.6%; headwords Mn-free everywhere |
| 4  | Diacritic folding policy? | **Per-language**: Latin full-fold ON; AR/RU/JA/EN off | LA 23→97.7% (P4); EN P4 manufactures false joins (tía→tia) |
| 5  | Name→C rescue worth building? | **Yes (LA/RU/AR/EN) via POSITIVE selection**; JA deferred to compositional path | CAT+M+DESC volumes; JA gloss route = 3 senses |
| 6  | Rule-12 double-catch material? | **EN + LA only** | EN 27,503 · LA 1,063 · RU 86 · JA 11 · AR 0 |
| 7  | Root-selection primary path viable? | **Yes, strongly** | EN translations 100% sense-hinted; ru 142K/ja 69K/ar 42K/la 33K items |
| 8  | OMW corroboration viable? | **Yes ja + ar (2 sources); ILI bridge confirmed**; none ru/la | ILI: ja 100%, arb 100%, awn4 97.33%, OEWN 104,335 |
| 9  | Pivot fallback needed? | **Russian only** ⟲REVISED | AWN4 volume rescues Arabic; LA/JA well-supplied |
| 10 | JA romanization/soft-redirect placement? | **Both → TIER_A_POS** | leak = 152 romanization senses reaching C |

## 2. Source manifest / provenance

Kaikki per-language extracts (English Wiktionary edition, English glosses). Dump dates: <fill>.

| File | entries | senses | lang uniformity | gloss coverage |
|------|---------|--------|-----------------|----------------|
| kaikki-english.jsonl.gz  | 1,473,332 | 1,762,689 | en 100% | 99.94% |
| kaikki-latin.jsonl.gz    |   891,525 | 1,007,869 | la 100% | 99.45% |
| kaikki-russian.jsonl.gz  |   442,213 |   491,996 | ru 100% | 99.99% |
| kaikki-japanese.jsonl.gz |   197,819 |   235,429 | ja 100% | 77.18% |
| kaikki-arabic.jsonl.gz   |    76,354 |    98,823 | ar 100% | 58.59% |

Wordnet sources (WN-LMF, downloaded <fill date>):

| Source | id | entries | senses | synsets | ILI | license | notes |
|--------|-----|---------|--------|---------|-----|---------|-------|
| Japanese WordNet (via OMW v2.0) | omw-ja | 94,002 | 158,069 | 117,659 | 100% | wordnet (permissive+attrib) | lemma↔synset only; relations inherited via ILI; `+` morph-join convention |
| Arabic WordNet v2 (via OMW v2.0) | omw-arb | 18,000 | 37,335 | 9,916 | 100% | CC BY-SA 3.0 (share-alike!) | human-built; 3.77 senses/synset; vocalized |
| Arabic WordNet 4.0 | awn4 | 136,041 | 184,238 | 120,630 | 97.33% | CC BY 4.0 | AI-translated (Gemini+Claude) from OEWN 2024; full relation graph; vocalized (tashkeel) |
| Open English WordNet 2025 | oewn | — | — | ~120K | 104,335 indexed | (existing) | ILI format `ili="iN"`; ~16K new synsets are `ili="in"` (unindexed) |

Negative findings (recorded, not downloaded):
- RuWordNet (~50K synsets / 111.5K words): **non-commercial, email-gated distribution → BLOCKED for product.** Russian is Kaikki-only.
- Latin WordNet (Minozzi/Exeter, ~9K→30K lemmas): **DEFERRED** — GPL-ambiguous data license, PWN-offset (not ILI) alignment, non-LMF SQLite format. Revisit only if Latin tree proves thin (unlikely post-P4).

## 3. Evidence

### 3A. Tier composition & rule attribution (prune_attribution_probe)
Self-check passed on all 5 files (attributed rules == real classify on every sense).

| Lang | A | B | C | dominant A-driver | rule-7 total |
|------|-----|-----|-----|-------------------|--------------|
| EN | 41.78% | 26.40% | 31.82% | rule-4 form-of 39.88% | 1592 (0.09%) |
| LA | 92.99% | 1.39% | 5.62% | rule-4 form-of 91.96% (verb inflection flood) | 35 (0.00%) |
| RU | 83.11% | 2.68% | 14.20% | rule-4 form-of 82.30% | 70 (0.01%) |
| JA | 46.32% | 11.14% | 42.55% | rule-1 short-def 23.08% (glossless senses) | 369 (0.16%) |
| AR | 54.91% | 5.39% | 39.70% | rule-1 short-def 41.42% (58.6% gloss coverage) | 14 (0.01%) |

Rule-7 (isalpha gate) is a rounding error everywhere and mostly catches genuine junk
(dotted abbreviations, Judeo-Arabic in Hebrew script, semaphore/braille). It does NOT
need to be relaxed — see 3B for where the diacritic problem actually lives.

### 3B. Headword character census — the inverted-diacritic finding ⟲REVISED
Working assumption entering Stage 1 was that vocalized/decorated HEADWORDS would be
dropped. FALSE. Headwords are bare in every language (with-Mn: LA 0.00% / 26 of 891K;
RU 0.01% / 41; AR 0.00% / 1 of 76,236; JA negligible). The decoration lives in the
SYNONYM REFERENCES, not the headwords — so the fix belongs in the normalized JOIN KEY
(3C), not the classify gate. This also makes Mn-strip in the key globally SAFE: it
changes almost no headword's key, only repairs the reference side.

### 3C. Edge-join by normalization policy (arabic_edge_join_probe)
P1 = current normalize_text · P2 = +Mn-strip · P3 = +Arabic fold · P4 = +full NFD-fold.
Single-word join rates:

| Lang | P1 | P2 | P3 | P4 | diagnosis |
|------|-----|-----|-----|-----|-----------|
| EN | 98.57% | 98.57% | 98.57% | 98.58% | healthy; P4's +71 are FALSE joins (foreign loanwords colliding) |
| LA | 23.35% | 23.35% | 23.35% | **98.59%** | precomposed macrons on refs vs bare headwords → needs full fold |
| RU | 11.79% | **86.35%** | 86.35% | 86.40% | combining stress marks on refs → Mn-strip suffices |
| AR | 0.71% | **87.96%** | 88.26% | 88.30% | harakat on refs → Mn-strip suffices; folding +0.33pp (skip) |
| JA | 70.27% | 70.27% | 70.27% | 70.48% | no diacritic issue; residue = furigana `語(よみ)` + grammatical forms |

Policy: Mn-strip globally in the normalized key (safe, repairs AR+RU). Full NFD-fold
(decompose→strip Mn→recompose) for LATIN ONLY, because Latin's decoration is precomposed
(carries no Mn to strip) and global full-fold manufactures false joins (EN evidence).
Implement as per-language key policy or two-stage exact-then-folded lookup — NOT one
global destructive key.

### 3D. Root selection — translations coverage (scan_english)
Translation items total 3,524,685, **100% carrying a sense hint**. Per target:
la 32,981 · ru 142,507 · ja 69,271 · ar 41,786. Primary root-selection path (sense-scoped
Kaikki translations off the English entry) is viable for all four. Non-English files carry
0 translations (expected — kaikki hangs translations off English entries only).

### 3E. Synonym pool sizes (own-graph, scan_*) — gate-9 input
| Lang | senses w/ sense-level syns | sense-level syn refs |
|------|---------------------------|----------------------|
| EN | 8.28% | 657,619 |
| JA | 7.45% | 29,962 |
| AR | 3.94% | 8,473 (thin — but see wordnets) |
| RU | 2.18% | 18,664 (thin, no wordnet → pivot fallback) |
| LA | 0.88% | 36,355 (rate misleading: denom inflated by 683K verb forms; healthy post-P4) |

### 3F. Name rescue composition (name_gloss_probe, post-refinement)
Buckets: CATEGORICAL (semantically empty, e.g. "a surname") / CATEGORICAL+MEANING
("...equivalent to English X", "...meaning Y") / DESCRIPTIVE (deities, months, epithets).

| Lang | name senses | CAT | CAT+MEANING | DESCRIPTIVE |
|------|-------------|-----|-------------|-------------|
| EN | 270,886 | 62.95% | 379 | 36.91% (still has categorical residue) |
| LA | 18,981 | 74.46% | 209 | 24.44% (Aurora/Felix/Angelus class) |
| RU | 6,585 | 54.14% | 358 | 40.43% |
| AR | 2,849 | 47.46% | 128 | 48.05% |
| JA | 23,167 | 63.71% | **3** | 36.28% (gloss route empty — JA names are bare category statements) |

Design finding: categorical EXCLUSION converges slowly (endless toponym tail); POSITIVE
selection converges fast. Stage 4 separator = "rescue meaning-bearing shapes"
(equivalent-to-English / meaning-"..." / descriptive deities-months-epithets), NOT
"embed what survives exclusion." Under zero-review this fails safe (misses some names)
rather than unsafe (floods referential noise). JA excluded from gloss-rescue → its name
path is compositional (kanji semantics), a post-import feature.

### 3G. Rule-12 census (leading-capital backstop)
EN 27,503 (noun 15,991 / adj 10,583 / verb 708 / adv 221) · LA 1,063 (adj 647 / noun 406 /
adv 10) · RU 86 · JA 11 · AR 0. Material only for EN + LA; Stage 4b must route separator-
passing rule-12 senses (capitalized common nouns like Latin name-words) to C alongside
rule-9 name-POS senses.

### 3H. Japanese POS leak (follow-up cross-tab)
romanization → A 33,146 / B 2 / **C 152** ; soft-redirect → A 44,382 (all, but only
incidentally — taxonomy doesn't know the POS exists). Fix: add both `romanization` and
`soft-redirect` to TIER_A_POS. 152-sense leak (Latin-script rōmaji duplicates) removed;
soft-redirect A-routing becomes an explicit invariant. English untouched (neither POS
occurs in the English file) → Stage-2 English-byte-identical invariant holds.

### 3I. Wordnet sources & ILI bridge (omw_coverage_scan)
- omw-ja / omw-arb LMF files contain lemma↔synset membership only, no SynsetRelation
  elements — this is EXPECTED (OMW lemma files inherit relational structure from the
  PWN/ILI backbone). Within-language synonymy comes from co-membership (multiple lemmas
  per synset: arb 3.77, ja 1.34); cross-language corroboration comes from shared ILI.
  Hypernym/topical relations (which we've already excluded from traversal) are simply
  absent, costing nothing.
- awn4 is a self-contained net WITH a full relation graph (hyponym/hypernym 93,446 each;
  member/part holonymy; domain links) plus ILI. Volume source for Arabic; distinct
  provenance tier (AI-translated → discount in ranking if it underperforms).
- ILI bridge CONFIRMED: OEWN 104,335 indexed synsets, format `ili="iN"`; OMW files
  97–100% ILI in the same CILI namespace. Root corroboration = synset-ID equality.
  (Decisive set-intersection of ILI ids deferred to import stage; per-file coverage +
  confirmed OEWN count is sufficient to close gate 8.)
- Integration notes for import stage: wordnet lemmas are vocalized (tashkeel) → join bare
  Kaikki headwords via the Mn-strip key from 3C (confirms that decision). omw-ja uses `+`
  as a morpheme-join marker → importer must split on it.

## 4. Decisions handed forward

### To Stage 2 (classify + normalization; English-byte-identical invariant)
- Add NFC-normalization of lemma before classify (insurance; gate 1).
- Add `romanization` + `soft-redirect` to TIER_A_POS (gate 10).
- normalized-key function: NFC + casefold + **strip Mn** globally (gate 3); Latin-only
  full NFD-fold path or two-stage exact-then-folded lookup (gate 4). Verify EN normalized
  keys unchanged (EN headwords are Mn-free → expected no-op).
- Regression guard: re-run attribution probe on EN (tier split + histogram unchanged) and
  the 4 new languages (rescues land, nothing leaves C).

### To Stage 3 (Arabic graph + display)
- Arabic/Russian join repaired by the gate-3 key alone (no folding). Verify via
  kaikki_sense_relations on a bounded slice reproduces ~81% resolution.
- Orthographic folding NOT implemented (gate 4: +0.33pp, not worth it).
- Populate Language.script (currently hardcoded None) + frontend RTL for Arabic.

### To Stage 4 (proper-noun rescue)
- Positive-selection separator (gate 5) for LA/RU/AR/EN; route separator-passing rule-9
  AND rule-12 senses to C (gate 6). JA excluded (compositional path later).
- English backfill: flip already-imported Tier-B name senses per new rules + embed.

### To post-import engine work
- Root selection: Kaikki translations primary (gate 7) + OMW/ILI corroboration for ja/ar
  (gate 8); embedding-nearest fallback, marked in provenance.
- Pivot fallback: build for RUSSIAN only (gate 9). Arabic decision may revisit after AWN4
  edges imported and counted, but provisionally NOT needed.
- OMW as build-time source via `wn` library for LMF parsing; never a runtime dependency
  (all data lands in Postgres; app queries only Postgres).

## 5. Supersession log
- ⟲ REVISED (gate 2): harakat problem is NOT at the classify/headword layer. Kaikki Arabic
  headwords are bare; vocalization lives in synonym references. Fix moved from classify
  gate to normalized join key.
- ⟲ REVISED (gate 9): Arabic is NOT a pivot-fallback case. AWN4 (184K senses) resolves the
  thin-Kaikki-graph concern. Russian is the sole pivot-fallback language.
- ⟲ NOTE: "semantic redundancy" reclassified as core product property (see
  MULTILINGUAL_EXPANSION_MODEL.md §3), not a weakness.
- ⟲ NOTE (Stage 4): Japanese name rescue via gloss is a dead end (3 senses); not a failure
  but confirmation that JA names require compositional/kanji handling post-import.

## 6. Deferred beyond Stage 1
- Latin WordNet integration (license/format/alignment cost; revisit if Latin tree thin).
- Japanese furigana-reference normalization (3C residue; revisit if JA tree thin).
- Decisive OEWN↔OMW ILI set-intersection count (import stage).
- AWN4 vs omw-arb edge-yield comparison (import stage; informs Arabic pivot re-decision).
- Interleave policy for the merged multilingual result list (engine-design stage).