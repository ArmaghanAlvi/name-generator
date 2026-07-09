"""
Emit a human-readable labeling sheet for the gold slate.

Usage:
    cd backend
    python -m scripts.eval.dropdown_label_sheet > scripts/eval/dropdown_label_sheet.txt

Reads the SAME candidate set the live dropdown builds (fetch_sense_candidates),
and renders each sense exactly as the user will see it post-Stage-1. Labeling
against anything else would produce labels for a population that doesn't exist.
"""
from __future__ import annotations

import sys

from app.db.session import SessionLocal
from app.services.sense_display import sense_display_for
from app.services.sense_lookup import fetch_sense_candidates
from scripts.eval.dropdown_gold import SLATE


SNIPPET_WIDTH = 110


def main() -> int:
    if not SLATE:
        print("SLATE is empty — fill it in first.", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        for word, band in SLATE:
            candidates = fetch_sense_candidates(
                db,
                query=word,
                language_code="en",
                limit=500,
            )

            print(f"\n{'=' * 78}")
            print(f"## {word}   [{band}]   {len(candidates)} visible senses")
            print(f"{'=' * 78}")

            for position, candidate in enumerate(candidates, start=1):
                display = sense_display_for(candidate.sense, candidate.override)
                group = f"[{display.group_label}] " if display.group_label else ""

                print(
                    f"{position:>4}. id={candidate.sense.id:<8} "
                    f"{candidate.lexeme.part_of_speech:<5} "
                    f"loc={candidate.sense.source_locator}"
                )
                print(f"      {group}{display.definition[:SNIPPET_WIDTH]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())