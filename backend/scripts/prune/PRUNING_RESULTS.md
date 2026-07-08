# Pruning Roadmap — Closeout Summary

Completed: 2026-07-08 (Stages 1–7 + single-letter refinement)

## Before / After

| Metric               | Before (raw Kaikki import) | After (final) |
|-----------------------|----------------------------|----------------|
| Senses                | 1,762,689                  | 1,034,150      |
| Lexemes               | 1,473,331                  | 776,603        |
| Sense relations (edges)| 953,717                   | 750,510        |
| Sense embeddings       | 564,454                    | 560,853        |
| Visible senses         | 1,762,689 (no visibility split yet) | 560,853 |
| Hidden senses (Tier B) | —                           | 473,297        |

Tier-A survivor check (post-purge): **0 POS matches, 0 tag matches** — the
taxonomy fully holds; nothing junk remains in the database.

## What was removed

- **733,868 senses** deleted in the one-time backfill purge (Stage 4):
  inflected forms (form-of/alt-of, ~530k), abbreviations/initialisms/acronyms,
  affixes, function words, interjections, multiword expressions, vulgar/
  derogatory content, misspellings, and malformed/coded lemmas.
- **701,355 lexemes** removed as fully emptied by the sense purge.
- **236 additional senses / 139 lexemes** removed in a follow-on refinement:
  single Latin/Cyrillic/Greek letters used as abbreviations, grades, musical
  notes, and numeral symbols ("a", "b", "c"...). Single characters in other
  scripts (Shavian, and by design CJK/Arabic/Hebrew/etc. for future languages)
  were deliberately left untouched — confirmed via the two Shavian entries
  ("𐑸" = are, "𐑲" = eye) that correctly remain visible post-cleanup.
- **~147,000 dangling `sense_relations` edges** swept after the lexeme purge
  (edges whose target no longer resolves to any surviving lexeme).

## What was preserved but hidden (Tier B)

473,297 senses remain in the database but are hidden from the dropdown and
excluded from embedding: proper nouns (name/num POS), archaic/dated/
historical/dialectal/nonstandard/slang registers, multiword nouns and verbs
(kept specifically because they hold ~5.6% of all synonym edges and support
expansion), plural-only forms, and the alt-of "orphan rescue" population
(purely-variant spellings whose canonical form doesn't otherwise exist in
the database).

## Eval re-baseline

- `scripts/eval/corpus.py`: all 32 corpus words still resolve; 0 unresolved.
- `scripts/eval/metrics.py`: fresh sweep captured in
  `eval_baseline_postprune.json` (copied from `knob-center.metrics.json`).
  This is now the reference baseline for any future sensitivity work —
  pre-prune metrics are no longer a valid comparison point, since the
  candidate pool composition changed substantially.

## Finding for the next feature: duplicate-definition re-measurement

Pre-prune duplicate-definition count: 20,556 groups / 71,056 senses.
**Post-prune: 5,574 groups / 16,345 senses** (largest group: "draw", 38
copies) — confirming most original duplication was junk (surname ×N,
plural-of ×N) that the purge removed.

**Important finding, not yet acted on**: the *remaining* duplicate groups are
largely NOT redundant entries safe to collapse. Inspection of the top groups
(draw, cut, head, free, bear, run, be...) shows these are legitimate,
distinct senses of highly polysemous words that share identical *first-gloss*
text because Wiktionary groups fine-grained sub-senses under one shared
category header, and the importer's `definition = raw_glosses[0]` captures
only that shared header line, not the fuller distinguishing text underneath.

**Implication for the planned dropdown dedup feature**: naively collapsing
"identical definition" groups (the original plan from the start of this
project) would incorrectly merge distinct real senses of words like "draw"
(38 senses) into a single generic dropdown entry — the opposite of the
intended effect. Before implementing dedup/collapse logic, the next roadmap
needs to either (a) distinguish "true duplicates" (identical meaning,
typically etymology-split entries of the same word) from "shared-header
polysemy" (distinct meanings, coincidentally identical first-gloss text) —
possibly by looking at `raw_glosses` beyond index 0, or `raw_sense`'s fuller
structure — or (b) reconsider whether definition-text identity is the right
signal for collapsing at all.