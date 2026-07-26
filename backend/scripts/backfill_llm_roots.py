"""
Bounded, resumable backfill of the llm root rung over the THIN population
(no curated link, no shared ILI, no prior attempt). Breakdown 4.5, Step 7.

Resumable: root_llm_attempts is the ledger; rerunning skips resolved,
unresolved, and (unless --retry-errors) errored pairs. Rate control lives
in root_llm (ROOT_LLM_RPM); --limit bounds one session against your
provider's daily cap.

USAGE (from backend/):
  python3 scripts/backfill_llm_roots.py --targets la ru ja ar --limit 500
"""
from __future__ import annotations

import argparse, os, sys
from collections import Counter

from sqlalchemy import text

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal            # noqa: E402
from app.services.root_llm import resolve_llm_root # noqa: E402

_THIN_SQL = text("""
SELECT p.sense_id
FROM (
  SELECT s.id AS sense_id, lx.raw_entry AS raw_entry
  FROM senses s
  JOIN lexemes lx ON lx.id = s.lexeme_id
  JOIN sense_embeddings se ON se.sense_id = s.id
  WHERE lx.language_id = 1 AND s.visibility_status = 'visible'
) p
LEFT JOIN sense_selection_stats sel ON sel.sense_id = p.sense_id
WHERE NOT EXISTS (
        SELECT 1 FROM sense_translations st
        JOIN senses ds ON ds.lexeme_id = st.target_lexeme_id
        JOIN sense_embeddings de ON de.sense_id = ds.id
        WHERE st.sense_id = p.sense_id AND st.language_id = :lang_id
          AND st.target_lexeme_id IS NOT NULL
          AND ds.visibility_status = 'visible')
  AND NOT EXISTS (
        SELECT 1 FROM sense_synsets ss1
        JOIN sense_synsets ss2 ON ss2.ili = ss1.ili
        JOIN senses ts ON ts.id = ss2.sense_id
        JOIN lexemes tl ON tl.id = ts.lexeme_id
        JOIN sense_embeddings te ON te.sense_id = ts.id
        WHERE ss1.sense_id = p.sense_id AND tl.language_id = :lang_id
          AND ts.visibility_status = 'visible')
  AND NOT EXISTS (
        SELECT 1 FROM root_llm_attempts a
        WHERE a.sense_id = p.sense_id AND a.language_id = :lang_id
          AND a.status = ANY(:skip_statuses))
ORDER BY
  -- Tier 1: senses with any recorded dropdown selection go first, ranked
  -- by selection_count. Small population (84 senses total today, almost
  -- certainly dev/testing traffic) -- exhausts fast, not the main volume.
  (COALESCE(sel.selection_count, 0) = 0) ASC,
  COALESCE(sel.selection_count, 0) DESC,
  -- Tier 2 (the real volume): translation breadth on the ENGLISH entry
  -- across ALL Kaikki-documented languages, not just la/ru/ja/ar -- a
  -- proxy for "common headword" vs. long-tail/technical sense. word_search_stats
  -- omitted: 1 row / 3 searches is not enough signal to justify the join.
  COALESCE(json_array_length(p.raw_entry->'translations'), 0) DESC,
  p.sense_id
LIMIT :limit
""")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", nargs="+", default=["la", "ru", "ja", "ar"])
    ap.add_argument("--limit", type=int, default=500,
                    help="total calls this session, across all targets")
    ap.add_argument("--retry-errors", action="store_true")
    args = ap.parse_args()

    skip = ["resolved", "unresolved"] + ([] if args.retry_errors else ["error"])
    budget = args.limit
    tally: Counter = Counter()
    with SessionLocal() as db:
        db.execute(text("SET lock_timeout = '30s'"))
        lang_ids = {code: id_ for code, id_ in db.execute(
            text("SELECT code, id FROM languages WHERE code = ANY(:c)"),
            {"c": args.targets}
        ).all()}
        per_lang = max(budget // len(args.targets), 1)
        for code in args.targets:
            ids = [i for (i,) in db.execute(_THIN_SQL, {
                "lang_id": lang_ids[code], "limit": per_lang,
                "skip_statuses": skip})]
            for sid in ids:
                if budget <= 0:
                    break
                lex = resolve_llm_root(db, english_sense_id=sid,
                                       language_code=code)
                budget -= 1
                tally[f"{code}:{'resolved' if lex else 'miss'}"] += 1
                done = sum(tally.values())
                if done % 25 == 0:
                    print(f"[{done}/{args.limit}] {dict(tally)}", flush=True)
    print("final:", dict(tally))


if __name__ == "__main__":
    print("NOTE: senses/lexemes/glosses sent to the configured LLM API.")
    main()