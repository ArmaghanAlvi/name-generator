-- Stage 5: hide every Tier-B sense. A sense is visible iff Tier C.
-- Mirrors the Tier-B branch of prune_taxonomy.classify() (Tier A is
-- already deleted, so ordering vs Tier-A rules no longer matters).
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