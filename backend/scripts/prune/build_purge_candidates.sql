-- Canonical lemmas: lemmas that have at least one NON-alt-tagged sense.
DROP TABLE IF EXISTS prune_canonical_lemmas;
CREATE TABLE prune_canonical_lemmas AS
SELECT DISTINCT l.normalized_lemma
FROM lexemes l JOIN senses s ON s.lexeme_id = l.id
WHERE NOT (s.raw_tags::jsonb ?| array['alt-of','alternative']);
CREATE INDEX ON prune_canonical_lemmas (normalized_lemma);
ANALYZE prune_canonical_lemmas;

-- Alt-orphan RESCUE: purely-alt lexemes whose target lemma has no canonical
-- entry. These are KEPT (Tier B) rather than dropped.
DROP TABLE IF EXISTS prune_alt_orphan_lexemes;
CREATE TABLE prune_alt_orphan_lexemes AS
WITH purely_alt AS (
  SELECT l.id AS lexeme_id,
         max(COALESCE(s.raw_sense -> 'alt_of'  -> 0 ->> 'word',
                      s.raw_sense -> 'form_of' -> 0 ->> 'word'))
           FILTER (WHERE COALESCE(s.raw_sense -> 'alt_of'  -> 0 ->> 'word',
                                  s.raw_sense -> 'form_of' -> 0 ->> 'word') IS NOT NULL)
           AS target_word
  FROM lexemes l JOIN senses s ON s.lexeme_id = l.id
  GROUP BY l.id
  HAVING bool_and(s.raw_tags::jsonb ?| array['alt-of','alternative'])
)
SELECT p.lexeme_id
FROM purely_alt p
LEFT JOIN prune_canonical_lemmas c ON c.normalized_lemma = lower(p.target_word)
WHERE c.normalized_lemma IS NULL;
CREATE INDEX ON prune_alt_orphan_lexemes (lexeme_id);
ANALYZE prune_alt_orphan_lexemes;

-- The drop set: every Tier-A sense, EXCEPT senses on rescued orphan lexemes.
-- The CASE order mirrors classify()'s precedence exactly.
DROP TABLE IF EXISTS purge_candidates;
CREATE TABLE purge_candidates AS
SELECT s.id AS sense_id, s.lexeme_id,
  CASE
    WHEN length(btrim(coalesce(s.definition,''))) < 3 THEN 'empty_def'
    WHEN btrim(coalesce(l.lemma,'')) = '' THEN 'empty_lemma'
    WHEN lower(btrim(l.part_of_speech)) IN (
         'article','prep','pron','conj','det','particle','contraction','postp',
         'prefix','suffix','infix','interfix','circumfix',
         'symbol','character','punct',
         'phrase','prep_phrase','adv_phrase','proverb','intj') THEN 'pos_tier_a'
    WHEN s.raw_tags::jsonb ?| array[
         'form-of','alt-of','alternative','clipping','ellipsis',
         'misspelling','pronunciation-spelling','morpheme',
         'abbreviation','initialism','acronym','vulgar','derogatory'] THEN 'tag_tier_a'
    WHEN btrim(l.lemma) ~ '[0-9]' THEN 'digit_shape'
    WHEN btrim(l.lemma) LIKE '-%' OR btrim(l.lemma) LIKE '%-' THEN 'hyphen_edge'
    WHEN btrim(l.lemma) ~ '[^[:alpha:][:space:]''-]' THEN 'nonalpha_shape'
  END AS reason
FROM senses s
JOIN lexemes l ON l.id = s.lexeme_id
WHERE (
    s.lexeme_id NOT IN (SELECT lexeme_id FROM prune_alt_orphan_lexemes)
    OR NOT (s.raw_tags::jsonb ?| array['alt-of','alternative'])
    -- rescue only protects senses with NO other independent Tier-A trigger:
    OR lower(btrim(l.part_of_speech)) IN (
         'article','prep','pron','conj','det','particle','contraction','postp',
         'prefix','suffix','infix','interfix','circumfix',
         'symbol','character','punct',
         'phrase','prep_phrase','adv_phrase','proverb','intj')
    OR s.raw_tags::jsonb ?| array[
         'form-of','clipping','ellipsis','misspelling','pronunciation-spelling',
         'morpheme','abbreviation','initialism','acronym','vulgar','derogatory']
  )
  AND (
       length(btrim(coalesce(s.definition,''))) < 3
    OR btrim(coalesce(l.lemma,'')) = ''
    OR lower(btrim(l.part_of_speech)) IN (
         'article','prep','pron','conj','det','particle','contraction','postp',
         'prefix','suffix','infix','interfix','circumfix',
         'symbol','character','punct',
         'phrase','prep_phrase','adv_phrase','proverb','intj')
    OR s.raw_tags::jsonb ?| array[
         'form-of','alt-of','alternative','clipping','ellipsis',
         'misspelling','pronunciation-spelling','morpheme',
         'abbreviation','initialism','acronym','vulgar','derogatory']
    OR btrim(l.lemma) ~ '[0-9]'
    OR btrim(l.lemma) LIKE '-%' OR btrim(l.lemma) LIKE '%-'
    OR btrim(l.lemma) ~ '[^[:alpha:][:space:]''-]'
  );
CREATE INDEX ON purge_candidates (sense_id);
CREATE INDEX ON purge_candidates (lexeme_id);
ANALYZE purge_candidates;