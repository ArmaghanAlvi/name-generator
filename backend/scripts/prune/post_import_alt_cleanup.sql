-- Post-import orphan-rescue resolution for one language.
-- Usage: psql -v lang_code=hi -f post_import_alt_cleanup.sql
-- Deletes provisional alt senses whose target lemma EXISTS in this language
-- (they're redundant variant pointers); keeps the true orphans as hidden
-- Tier-B rows. Then removes lexemes left senseless.

WITH lang AS (
  SELECT id FROM languages WHERE code = :'lang_code'
),
canonical AS (
  SELECT DISTINCT l.normalized_lemma
  FROM lexemes l
  JOIN senses s ON s.lexeme_id = l.id
  WHERE l.language_id = (SELECT id FROM lang)
    AND NOT (s.raw_tags::jsonb ?| array['alt-of','alternative'])
),
provisional AS (
  SELECT s.id AS sense_id, s.lexeme_id,
         COALESCE(s.raw_sense -> 'alt_of'  -> 0 ->> 'word',
                  s.raw_sense -> 'form_of' -> 0 ->> 'word') AS target_word
  FROM senses s
  JOIN lexemes l ON l.id = s.lexeme_id
  WHERE l.language_id = (SELECT id FROM lang)
    AND s.visibility_status = 'hidden'
    AND s.raw_tags::jsonb ?| array['alt-of','alternative']
)
DELETE FROM senses
WHERE id IN (
  SELECT p.sense_id FROM provisional p
  JOIN canonical c ON c.normalized_lemma = lower(p.target_word)
);

-- Sweep lexemes emptied by the delete (small per-language; batching not
-- needed thanks to ix_sense_relations_target_lexeme).
DELETE FROM lexemes l
WHERE l.language_id = (SELECT id FROM languages WHERE code = :'lang_code')
  AND NOT EXISTS (SELECT 1 FROM senses s WHERE s.lexeme_id = l.id);