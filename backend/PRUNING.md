# Pruning & Import-Time Tier Gate — Contract Document

This document is the single source of truth for how NameForge decides what
enters the database, what stays hidden, and what gets embedded. It exists so
a future language import (or a future contributor) never has to re-derive
these decisions from scratch.

## The three tiers

Every sense from any source is classified into exactly one tier, defined in
`app/services/prune_taxonomy.py` (`classify()`), and enforced by both the
Kaikki importer (import-time gate) and the embedding pipeline
(`is_name_worthy()` in `app/services/sense_embeddings.py`).

| Tier | Meaning | Stored? | Visible in dropdown? | Embedded? |
|------|---------|---------|----------------------|-----------|
| A | Never belongs in the DB, regardless of language | No — dropped at import (or deleted in the one-time backfill purge for English) | — | — |
| B | Real content, but not a name candidate | Yes | No (`visibility_status='hidden'`) | No |
| C | A genuine single-word name candidate | Yes | Yes (`visibility_status='visible'`) | Yes |

**Zero-review constraint**: every rule below is a category-level predicate
over POS, tags, lemma shape, or definition length — never a per-word judgment
call. New languages get the same rules applied mechanically; no manual
review of individual words is required or expected.

## Tier A — hard-drop (never enters the database)

### Parts of speech
Function words: `article, prep, pron, conj, det, particle, contraction, postp`
Affixes/combining forms: `prefix, suffix, infix, interfix, circumfix`
Standalone glyphs: `symbol, character, punct`
Multiword expressions: `phrase, prep_phrase, adv_phrase, proverb`
Expressive noises: `intj`

### Tags (sense-level; ride on any POS)
`form-of, alt-of, alternative, clipping, ellipsis, misspelling,
pronunciation-spelling, morpheme, abbreviation, initialism, acronym,
vulgar, derogatory`

### Shape rules
- Definition under 3 characters (empty/near-empty gloss)
- Empty lemma
- Lemma contains a digit (coded entries: `s620s`, `-4j`)
- Lemma starts or ends with a hyphen (affix-shaped: `-ing`, `un-`)
- Lemma contains any character that isn't a letter, hyphen, apostrophe, or space
  (dotted abbreviations, symbols: `Det.`, `S.F.X.`)
- Lemma is a single Latin, Cyrillic, or Greek letter (e.g. "a", "b", "e") —
  these are letters/abbreviations/musical notes, never names. Implemented via
  Unicode character-name script detection (`_is_western_single_letter`), NOT a
  raw length check — single characters in CJK, Arabic, Hebrew, Devanagari, and
  Hangul scripts are frequently complete words and are deliberately NOT caught.
  **Caveat**: Greek is included in the drop-set because it is not one of the 20
  planned languages (a lone Greek letter here is a math/physics symbol). If
  Greek is ever added as a language, this rule needs a per-language exception,
  same pattern as the capitalization backstop.

### The alt-of orphan rescue (exception to the alt-of/alternative rule)
A sense tagged `alt-of`/`alternative` is normally Tier A (it's a spelling
variant of something else — e.g. "colour" pointing at "color"). **Exception**:
if that sense's target word does not exist anywhere else in the database
(the variant is the *only* form of the word we have), it is rescued to
**Tier B** instead of dropped — losing it would mean deleting a real,
otherwise-unreachable word.

**Critical scoping rule** (this was a real bug, caught and fixed during the
English backfill purge — see `git log` for "rescue-scope fixed"): the rescue
applies **only when alt-of/alternative is the sense's *sole* Tier-A trigger**.
A sense that is *also* an abbreviation, an initialism, on a Tier-A POS, etc.
is NOT rescued — it's still Tier A regardless of its alt-of tag. Example:
"FFS" (abbreviation + alt-of) is correctly dropped; "colour" (alt-of only,
with no canonical twin in-DB in some hypothetical scenario) would be rescued.

This logic lives in `sole_alt_trigger()` in `prune_taxonomy.py`. Because the
importer processes one file top-to-bottom and can't know in advance whether
a target word appears later in the same file, it cannot make the final
orphan/non-orphan call during import. Instead:
1. **At import time**: any sense where `sole_alt_trigger()` is true is kept
   as **provisional** — stored, `visibility_status='hidden'` — rather than
   dropped or fully resolved.
2. **After the full file is imported**: run `post_import_alt_cleanup.sql`
   for that language. It deletes provisional senses whose target word DOES
   exist elsewhere in that language (they were non-orphans after all) and
   leaves the true orphans in place as permanent Tier-B rows.

**Always run `post_import_alt_cleanup.sql` immediately after importing a new
language's full file.** Skipping this step leaves non-orphan variant senses
sitting in the DB — harmless (they're hidden either way) but wasted rows.

## Tier B — keep, don't embed, hidden from the dropdown

### Parts of speech
`name` (proper nouns: places, surnames, given names — genuinely mixed
content, some evocative geography, mostly boilerplate; kept for possible
future use, e.g. a "places/names" mode, but excluded from the default
name-search experience)
`num` (number words: "seven", "trillion" — some real meaning, thin name value)

### Tags
`slang, obsolete, archaic, dated, historical, nonstandard, dialectal,
plural-only, in-plural` — these are real meanings in registers we don't
want surfacing in a general-purpose name search, but which may have future
value (a "vintage/archaic names" mode, etymology work, the `roots` table).

### Shape rule
Multiword lemmas (`lemma LIKE '% %'`) — e.g. "soft drink", "speed up".
**Note**: multiword lexemes hold a non-trivial share of synonym edges
(~5.6% of all edges as measured on the English data, concentrated in
phrasal verbs like "speed up" → accelerate). They are kept specifically so
root-mode expansion can still traverse through them, even though they never
appear as name candidates themselves.

### Capitalization backstop
A lemma under a common POS (e.g. `noun`) whose first letter is capitalized
but which is not all-caps (ruling out acronyms, already Tier A via tags) is
treated as a likely proper noun and moved to Tier B, even without an
explicit `name` POS. **Language-specific caveat**: this rule assumes only
proper nouns are capitalized. It is inert or safe for all languages
currently planned (see the "20 languages" list below) — none capitalizes
common nouns the way German does, and the caseless-script languages
(Arabic, Hebrew, Sanskrit, Japanese, Chinese, Korean) never trigger it at
all. **If a future language capitalizes common nouns, this rule needs a
per-language exception before that language is imported.**

## Tier C — kept, visible, embedded

Everything that survives all of the above. This is the actual name-candidate
pool.

## The two enforcement points

1. **`app/services/prune_taxonomy.py`** — `classify()` is the single source
   of truth. Both of the below defer to it; neither should ever define its
   own exclusion rules again.
2. **`app/services/sense_embeddings.py`** — `is_name_worthy()` returns
   `classify_sense(sense) is Tier.C`. The vector index only ever contains
   Tier-C senses.
3. **`app/importers/kaikki_english.py`** — `import_kaikki_file()` applies
   `classify()` per sense before any row is written: Tier A senses are
   skipped entirely (never created); if *every* sense of an entry is Tier A,
   the entire entry (and its lexeme) is skipped; Tier B senses are created
   with `visibility_status='hidden'`; Tier C senses are created `'visible'`.
   A `--dry-run` flag classifies and counts without writing anything
   (implemented via `db.rollback()` at the end rather than skipped writes,
   so it's safe even if a future code change adds a new write path).

Despite the filename, `kaikki_english.py`'s importer logic is
language-agnostic — `classify()` takes plain pos/tags/lemma/definition
strings, not English-specific structures. The Kaikki JSONL schema is the
same across their per-language dumps. Renaming or generalizing the module
is a nice-to-have for the 19-language rollout, not a functional requirement.

## Pipeline for importing a new language

1. Download the language's Kaikki JSONL(.gz) dump.
2. Run the importer against it (the gate applies automatically — Tier A
   never enters the DB, Tier B enters hidden, Tier C enters visible).
   Consider a `--dry-run` pass first to sanity-check tier proportions
   against this document's expectations before committing to a live run.
3. Run `post_import_alt_cleanup.sql -v lang_code=<code>` to resolve the
   alt-of orphan rescue for that language.
4. Run the embedding backfill (`backfill_sense_embeddings.py
   --language-code <code>`) — it will only embed Tier-C senses, automatically,
   via `is_name_worthy()`.
5. If an OEWN-equivalent wordnet resource exists for the language, run the
   equivalent of `load_oewn_relations.py` for synonym edges — ensure any
   such loader filters `visibility_status == 'visible'` when building its
   lemma index (see the fix applied for English in `load_oewn_relations.py`,
   Stage 5 of the original pruning work — the same fix is needed for any
   new per-language relation loader).
6. Re-run the census-style sanity queries (see `scripts/prune/` for the
   originals) to confirm proportions look sane for the new language before
   considering the import complete.

## Known scale, for reference (English, post-purge, as of this document)

- Total senses before pruning: 1,762,689
- Tier-A senses removed (backfill purge + single-letter refinement): 734,104
  (733,868 + 236)
- Tier-B senses kept, hidden: ~208,631 `name` + additional register/multiword/
  rescued-alt senses (see `scripts/prune/stage1_findings.md` for exact figures)
- Lexemes removed: 701,494 (701,355 + 139)
- Embeddable (Tier-C) senses: ~560,000–565,000
- Final senses: 1,034,150 (560,853 visible / 473,297 hidden)
- Final lexemes: 776,603
- Final sense_relations: 750,510
- Final sense_embeddings: 560,853

Full before/after detail: `scripts/prune/PRUNING_RESULTS.md`.

These numbers are specific to the English Kaikki extract and will not
generalize proportionally to other languages — treat them as a sanity-check
reference, not an expected ratio. (Observed on a 100k-line slice: Tier-A
share varied from ~13–15% near the start of the file to a corpus-wide ~40%,
since Kaikki's internal entry ordering is not representative of overall
composition — always validate a new language's real proportions rather than
assuming they'll match English's.)

These numbers are specific to the English Kaikki extract and will not
generalize proportionally to other languages — treat them as a sanity-check
reference, not an expected ratio. (Observed on a 100k-line slice: Tier-A
share varied from ~13–15% near the start of the file to a corpus-wide ~40%,
since Kaikki's internal entry ordering is not representative of overall
composition — always validate a new language's real proportions rather than
assuming they'll match English's.)

## History and lessons (for anyone debugging this system later)

- The alt-of orphan rescue was originally implemented as a blanket
  lexeme-level exclusion, which incorrectly protected senses that were
  *independently* Tier A for other reasons (abbreviations, initialisms,
  Tier-A POS). Fixed by scoping the rescue to apply only when alt-of is the
  *sole* trigger — see `sole_alt_trigger()`.
- `sense_relations.target_lexeme_id` had no supporting index despite being
  the target of an `ON DELETE SET NULL` foreign key, which made bulk lexeme
  deletion pathologically slow (full table scans per deleted row). An index
  (`ix_sense_relations_target_lexeme`) was added; this should be included
  in any fresh schema/migration baseline, not just left as a manual fix.
- `docker exec -i psql -c "..."` is not safely interruptible — Ctrl-C
  detaches the client but does not cancel the backend query. Long-running
  maintenance queries should be run with `SET lock_timeout = '...'` and,
  if they need to be stopped, terminated via `pg_terminate_backend()` from
  a second session rather than Ctrl-C.