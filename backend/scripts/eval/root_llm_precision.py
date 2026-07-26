"""
LLM-rung precision probe (Breakdown 4.5, Step 5). READ-ONLY -- no
root_llm_attempts rows, no sense_translations writes.

METHOD: identical to root_fallback_precision.py -- sample English senses
that HAVE a resolved translation link (correct answers KNOWN), ask the LLM
as if no link existed, resolve its proposals in memory, and check agreement
with the linked lexemes. Reports per language:
  resolve_rate     proposals that resolve to ANY real lexeme+display sense
  precision_top1   first RESOLVING proposal is a linked lexeme
  precision_any    any proposal resolves to a linked lexeme
Same favorable-sample caveat as the fallback probe -- which is the point:
identical exam, so the 15-19% comparison is apples to apples.

USAGE: python3 scripts/eval/root_llm_precision.py [--n 60] [--targets la ru ja ar]
"""
from __future__ import annotations

import argparse, os, sys
from collections import defaultdict

from sqlalchemy import func, select

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal                        # noqa: E402
from app.models.generated_name import Language                 # noqa: E402
from app.models.semantic import (                              # noqa: E402
    Lexeme, Sense, SenseTranslation,
)
from app.services.root_llm import propose_translations         # noqa: E402
from app.services.root_selection import _display_sense         # noqa: E402
from app.utils.text import normalize_lemma                     # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--targets", nargs="+", default=["la", "ru", "ja", "ar"])
    args = ap.parse_args()

    with SessionLocal() as db:
        for code in args.targets:
            lang = db.scalars(select(Language).where(Language.code == code)).first()
            # Sampled senses WITH >=1 resolved curated link (the answer key).
            rows = db.execute(
                select(SenseTranslation.sense_id,
                       func.array_agg(SenseTranslation.target_lexeme_id))
                .where(SenseTranslation.language_id == lang.id, # type: ignore
                       SenseTranslation.target_lexeme_id.isnot(None),
                       SenseTranslation.attachment != "llm")
                .group_by(SenseTranslation.sense_id)
                .order_by(func.random()).limit(args.n)
            ).all()

            stats = defaultdict(int)
            for sense_id, linked_ids in rows:
                sense = db.get(Sense, sense_id)
                gloss = (
                    (sense.definition or "").strip()  # type: ignore[reportOptionalMemberAccess]
                    or (sense.raw_glosses[0] if sense.raw_glosses else "") # type: ignore[reportOptionalMemberAccess]
                ) 
                try:
                    proposed, _served_model = propose_translations(
                        lemma=sense.lexeme.lemma, # type: ignore
                        pos=sense.lexeme.part_of_speech, # type: ignore
                        gloss=gloss, language_name=lang.name) # type: ignore
                except Exception as exc:
                    stats["errors"] += 1
                    print(f"  [{code}] sense={sense_id} error: "
                          f"{type(exc).__name__}: {exc}", file=sys.stderr)
                    continue
                stats["asked"] += 1
                resolved = []
                for w in proposed:
                    lex_id = db.scalar(
                        select(Lexeme.id)
                        .where(Lexeme.language_id == lang.id, # type: ignore
                               Lexeme.normalized_lemma ==
                               normalize_lemma(w, lang.code)) # type: ignore
                        .order_by(Lexeme.id).limit(1))
                    if lex_id is not None and _display_sense(db, lex_id):
                        resolved.append(lex_id)
                if resolved:
                    stats["resolved_any"] += 1
                    if resolved[0] in set(linked_ids):
                        stats["top1_hit"] += 1
                    if set(resolved) & set(linked_ids):
                        stats["any_hit"] += 1

            a = max(stats["asked"], 1)
            r = max(stats["resolved_any"], 1)
            print(f"{code}: asked={stats['asked']} errors={stats['errors']} "
                  f"resolve_rate={stats['resolved_any']/a:.0%} "
                  f"precision_top1={stats['top1_hit']/r:.0%} "
                  f"precision_any={stats['any_hit']/r:.0%}")


if __name__ == "__main__":
    main()