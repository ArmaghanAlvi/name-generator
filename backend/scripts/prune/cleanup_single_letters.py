"""Delete length-1 senses that classify Tier A under the current taxonomy
(single Latin/Cyrillic/Greek letters). Reuses classify_sense() as the single
source of truth. Preview-only unless --execute is passed."""
from __future__ import annotations
import argparse
from sqlalchemy import select, func, delete as sa_delete
from sqlalchemy.orm import selectinload
from app.db.session import SessionLocal
from app.models.semantic import Lexeme, Sense
from app.services.prune_taxonomy import classify_sense, Tier


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="Actually delete (default is preview only).")
    args = ap.parse_args()

    with SessionLocal() as db:
        senses = db.scalars(
            select(Sense)
            .options(selectinload(Sense.lexeme))
            .join(Lexeme, Lexeme.id == Sense.lexeme_id)
            .where(func.length(Lexeme.normalized_lemma) == 1)
        ).all()

        to_delete = [s for s in senses if classify_sense(s) is Tier.A]
        print(f"length-1 senses examined: {len(senses)}")
        print(f"now-Tier-A (to delete):   {len(to_delete)}")
        for s in to_delete[:20]:
            print(f"  DELETE  {s.lexeme.normalized_lemma!r} "
                  f"[{s.lexeme.part_of_speech}] {(s.definition or '')[:50]}")

        if not args.execute:
            print("\nPreview only. Re-run with --execute to delete.")
            return

        sense_ids = [s.id for s in to_delete]
        lexeme_ids = {s.lexeme_id for s in to_delete}
        db.execute(sa_delete(Sense).where(Sense.id.in_(sense_ids)))
        db.flush()  # let sense deletes land before checking empty lexemes

        # sweep lexemes left with zero senses
        empty = db.scalars(
            select(Lexeme.id).where(
                Lexeme.id.in_(lexeme_ids),
                ~select(Sense.id).where(Sense.lexeme_id == Lexeme.id).exists(),
            )
        ).all()
        if empty:
            db.execute(sa_delete(Lexeme).where(Lexeme.id.in_(empty)))
        db.commit()
        print(f"\nDeleted {len(sense_ids)} senses, {len(empty)} emptied lexemes.")


if __name__ == "__main__":
    main()