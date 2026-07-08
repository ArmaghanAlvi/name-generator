-- Batched deletion of Tier-A senses. CASCADE handles embeddings, selection
-- stats/events, admin overrides, tags, and outbound edges automatically.
DO $$
DECLARE
  batch_size int := 20000;
  deleted int;
  total int := 0;
BEGIN
  LOOP
    DELETE FROM senses
    WHERE id IN (
      SELECT sense_id FROM purge_candidates
      WHERE sense_id IN (SELECT id FROM senses)
      LIMIT batch_size
    );
    GET DIAGNOSTICS deleted = ROW_COUNT;
    total := total + deleted;
    RAISE NOTICE 'deleted % senses (running total: %)', deleted, total;
    EXIT WHEN deleted = 0;
  END LOOP;
  RAISE NOTICE 'DONE: % senses deleted', total;
END $$;

-- Delete lexemes with zero remaining senses. Batched. Triggers SET NULL on
-- any inbound sense_relations.target_lexeme_id (swept in Step 4).
DO $$
DECLARE
  batch_size int := 20000;
  deleted int;
  total int := 0;
BEGIN
  LOOP
    DELETE FROM lexemes
    WHERE id IN (
      SELECT l.id FROM lexemes l
      WHERE NOT EXISTS (SELECT 1 FROM senses s WHERE s.lexeme_id = l.id)
      LIMIT batch_size
    );
    GET DIAGNOSTICS deleted = ROW_COUNT;
    total := total + deleted;
    RAISE NOTICE 'deleted % lexemes (running total: %)', deleted, total;
    EXIT WHEN deleted = 0;
  END LOOP;
  RAISE NOTICE 'DONE: % lexemes deleted', total;
END $$;