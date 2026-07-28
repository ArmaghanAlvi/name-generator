-- Stage 5: hide every Tier-B sense. A sense is visible iff Tier C.
-- Mirrors the Tier-B branch of prune_taxonomy.classify() (Tier A is
-- already deleted, so ordering vs Tier-A rules no longer matters).
-- ⚠ DO NOT RUN AFTER THE 15-LANGUAGE BATCH BEGINS.
-- The capitalization clause below mirrors prune_taxonomy rule 12, which as of
-- the 15-language batch is LANGUAGE-CONDITIONED (exempt: German, and any
-- future common-noun-capitalizing language — see _CAPITALIZES_COMMON_NOUNS).
-- This file has no language filter and would hide every German noun.
-- Retained as a historical record of the original Stage 5 prune. If a Tier-B
-- sweep is ever needed again, drive it from classify_sense() in Python with a
-- language code, not from this SQL.
UPDATE senses s
SET visibility_status = 'hidden'
FROM lexemes l
WHERE l.id = s.lexeme_id
  AND s.visibility_status = 'visible'
  AND (
       lower(btrim(l.part_of_speech)) IN ('name', 'num')
    OR s.raw_tags::jsonb ?| array[
         'slang','obsolete','archaic','dated','historical','nonstandard',
         'dialectal','plural-only','in-plural']
    OR btrim(l.lemma) LIKE '% %'
    OR (left(btrim(l.lemma), 1) ~ '[[:upper:]]'
        AND btrim(l.lemma) <> upper(btrim(l.lemma)))
    OR s.raw_tags::jsonb ?| array['alt-of','alternative']  -- rescued orphans
  );