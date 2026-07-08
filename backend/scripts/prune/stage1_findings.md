# Stage 1 Findings — Database Pruning

Date:
DB snapshot before purge: (filled in Stage 3)

## Step 2 — alt-of orphan check
- purely_alt_lexemes: 146430
- unresolvable_no_target_key: 14
- safe_target_present: 127662
- true_orphans: 18754  (upper bound — normalization mismatch can only overcount)
- alt_of raw_sense shape confirmed: [x] `[{"word": "..."}]`
- VERDICT: [x] needs Tier-B-keep-orphans refinement
  -> classify() will keep (Tier B, unembedded) any purely-alt-tagged lexeme
     whose target word has no non-alt-tagged lexeme in the DB.

## Step 3 — FK delete-behavior census
- lexemes -> senses (senses_lexeme_id_fkey): CASCADE
- lexemes -> sense_relations.target_lexeme_id: SET NULL   <-- only non-cascading FK
- senses -> sense_selection_stats: CASCADE
- senses -> sense_selection_events: CASCADE
- senses -> sense_admin_overrides: CASCADE
- senses -> sense_tags: CASCADE
- senses -> sense_embeddings: CASCADE
- senses -> sense_relations.from_sense_id: CASCADE

- DELETION ORDER for Stage 4:
  1. Delete Tier-A senses (all listed CASCADEs fire automatically: embeddings,
     selection stats/events, admin overrides, tags, outbound edges)
  2. Delete lexemes with zero remaining senses (fires SET NULL on inbound
     sense_relations.target_lexeme_id)
  3. Post-sweep: compare null target_lexeme_id count to Step 5 baseline;
     decide whether to delete newly-nulled/unreachable edge rows
  - No pre-delete pass needed — every child FK except target_lexeme_id cascades.

## Step 4 — multiword-noun decision
- edges_from_multiword_senses: 53086
- total_edges: 953717
- share %: 5.6%
- sample: top edge-holders are mostly real phrasal verbs (speed up, get up,
  pick up, take in, make out, come to) with genuine synonym targets, plus
  a few compound nouns (soft drink, old man, common law)
- DECISION: [x] Tier B (keep, don't embed) — pending final confirmation
  Rationale: >5% edge share, top holders are real expansion springboards,
  not junk compounds. Storage cost of keeping (unembedded rows) is low.

## Step 5 — NULL-target baseline
- total_edges: 953717
- null_target_edges (baseline): 85585

## Step 6 — taxonomy lock
- multiword lexemes: Tier B (keep, don't embed)
- clipping: Tier A (drop)
- ellipsis: Tier A (drop)
- nonstandard: Tier B (keep, don't embed)
- alt-of orphan refinement: adopted (purely-alt lexeme with absent target -> Tier B)
- TAXONOMY: [x] locked


## Stage 3 — dry-run sizing (final, post-fix)
- senses_to_drop: 733868
- lexemes_fully_emptied: 701355
- embeddings_removed: 3486
- outbound_edges_cascaded: 55560
- reason breakdown: tag_tier_a 700579, pos_tier_a 28560, digit_shape 2015,
  nonalpha_shape 1601, empty_def 1100, hyphen_edge 13
- Parity check: 0 mismatches, 0 newly-embedded (confirmed post rescue-scope fix)