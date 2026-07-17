"""Post-import orphan-rescue resolution for one language, using the CANONICAL
join key.

Supersedes post_import_alt_cleanup.sql, which compared lower(target_word)
against Lexeme.normalized_lemma. lower() is NOT normalize_lemma: it keeps
Arabic harakat, Russian stress marks and Latin macrons, so a decorated
alt-target cannot match its bare canonical headword and the redundant
provisional sense is kept instead of deleted. Same join-key fork class as
IMPORT_PREP_FINDINGS.md 6.3, one layer down.

Deletes provisional alt senses whose target lemma EXISTS in this language
(redundant variant pointers); keeps true orphans as hidden rows. Then removes
lexemes left senseless.

MUST run BEFORE kaikki_sense_relations.py for the language: deleting a sense
cascades its edges away, and deleting a lexeme SET NULLs every edge pointing
at it -- silently un-resolving edges that were correctly resolved.

Dry-run by default; the dry run IS the measurement (reports both policies).
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from sqlalchemy import delete, select, text

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal              # noqa: E402
from app.models.generated_name import Language       # noqa: E402
from app.models.semantic import Lexeme, Sense        # noqa: E402
from app.utils.text import normalize_lemma           # noqa: E402

# Mirrors prune_taxonomy._ALT_TAGS (private there). Keep in sync.
_ALT_TAGS = frozenset({"alt-of", "alternative"})


def target_word_of(raw_sense: dict[str, Any]) -> str | None:
    """The lemma a variant sense points AT. Mirrors the SQL's COALESCE of
    raw_sense->alt_of->0->>word, raw_sense->form_of->0->>word."""
    for key in ("alt_of", "form_of"):
        items = raw_sense.get(key) or []
        if items and isinstance(items[0], dict):
            word = items[0].get("word")
            if word:
                return str(word)
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--language-code", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="write changes; default is dry-run (measure only)")
    ap.add_argument("--examples", type=int, default=10)
    args = ap.parse_args()

    with SessionLocal() as db:
        db.execute(text("SET lock_timeout = '30s'"))

        lang = db.scalars(
            select(Language).where(Language.code == args.language_code)
        ).first()
        if lang is None:
            raise SystemExit(f"No Language row with code={args.language_code!r}")

        # Pass 1: canonical keys = normalized_lemma of every lexeme in this
        # language holding at least one NON-alt-tagged sense. raw_tags only --
        # raw_sense is deliberately not selected here (it is the heavy column).
        canonical: set[str] = set()
        for norm, tags in db.execute(
            select(Lexeme.normalized_lemma, Sense.raw_tags)
            .join(Sense, Sense.lexeme_id == Lexeme.id)
            .where(Lexeme.language_id == lang.id)
        ).yield_per(5000):
            tagset = {str(t).strip().lower() for t in (tags or [])}
            if not (tagset & _ALT_TAGS):
                canonical.add(norm)

        # Pass 2: provisional alt senses (hidden + alt-tagged + has a target).
        total_alt = 0
        no_target = 0
        del_canonical: list[int] = []
        del_lower: set[int] = set()
        samples: list[tuple[str, str, str]] = []

        for sense_id, tags, raw_sense in db.execute(
            select(Sense.id, Sense.raw_tags, Sense.raw_sense)
            .join(Lexeme, Lexeme.id == Sense.lexeme_id)
            .where(
                Lexeme.language_id == lang.id,
                Sense.visibility_status == "hidden",
            )
        ).yield_per(2000):
            tagset = {str(t).strip().lower() for t in (tags or [])}
            if not (tagset & _ALT_TAGS):
                continue
            total_alt += 1
            target = target_word_of(raw_sense or {})
            if not target:
                no_target += 1
                continue

            key_canonical = normalize_lemma(target, lang.code)
            key_lower = target.lower()

            hit_canonical = key_canonical in canonical
            hit_lower = key_lower in canonical

            if hit_canonical:
                del_canonical.append(sense_id)
            if hit_lower:
                del_lower.add(sense_id)
            if hit_canonical and not hit_lower and len(samples) < args.examples:
                samples.append((target, key_lower, key_canonical))

        delta = len(set(del_canonical) - del_lower)

        print(f"language ......................... {lang.code} (id={lang.id})")
        print(f"canonical keys ................... {len(canonical)}")
        print(f"provisional alt senses (hidden) .. {total_alt}")
        print(f"  with no alt_of/form_of target .. {no_target}")
        print(f"would delete under lower() ....... {len(del_lower)}   [old SQL]")
        print(f"would delete under canonical key . {len(del_canonical)}   [this script]")
        print(f"  rows the old SQL MISSED ........ {delta}")
        print("  samples (target -> lower key | canonical key):")
        for t, lo, ca in samples:
            print(f"    {t!r} -> {lo!r} | {ca!r}")

        if not args.apply:
            print("\nDRY RUN -- nothing written. Re-run with --apply to commit.")
            return

        if del_canonical:
            for i in range(0, len(del_canonical), 5000):
                db.execute(delete(Sense).where(Sense.id.in_(del_canonical[i:i + 5000])))
            db.commit()

        # Sweep lexemes emptied by the delete.
        orphaned = db.scalars(
            select(Lexeme.id).where(
                Lexeme.language_id == lang.id,
                ~select(Sense.id).where(Sense.lexeme_id == Lexeme.id).exists(),
            )
        ).all()
        if orphaned:
            for i in range(0, len(orphaned), 5000):
                db.execute(delete(Lexeme).where(Lexeme.id.in_(list(orphaned[i:i + 5000]))))
            db.commit()

        print(f"\nApplied: {len(del_canonical)} senses deleted, "
              f"{len(orphaned)} senseless lexemes swept.")


if __name__ == "__main__":
    main()