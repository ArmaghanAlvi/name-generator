"""
Kaikki translations extractor: ENGLISH senses -> sense_translations rows for
ONE target language. DB-side (reads raw_sense / raw_entry; never streams the
file). Dry-run by default; the dry run is the measurement.

Two channels (Breakdown 4, Steps 1b/1e):
  SENSE-LEVEL  senses[].translations on Sense.raw_sense -- already scoped,
               attachment 'sense'. The bulk channel.
  ENTRY-LEVEL  Lexeme.raw_entry['translations'] -- routed to a sense by
               _dis1 argmax ('dis1'), else exact hint-vs-gloss match
               ('hint'), else EXCLUDED (counted as unrouted). sense_index
               is 1-based file order incl. dropped senses (verified against
               kaikki_english.py), so _dis1 positions map onto stored
               sense_index directly. Routed targets must be VISIBLE senses;
               routes to dropped/hidden indices fall through to exclusion.

Visible English senses only: roots anchor on dropdown-pickable senses, and
the pivot's reverse read must land on an expandable sense.

Idempotent: in-memory dedup + ON CONFLICT DO NOTHING on
uq_sense_translations_link. Re-run skips; it does not repair (if the target
language's lexemes changed, DELETE that language's rows and re-extract).

USAGE (from backend/):
  python3 -m app.extractors.kaikki_translations \
      --target-language-code la [--apply] [--commit-every 5000]
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal                        # noqa: E402
from app.models.generated_name import Language                 # noqa: E402
from app.models.semantic import Lexeme, Sense, SenseTranslation, Source  # noqa: E402
from app.utils.text import normalize_lemma, normalize_text     # noqa: E402


# Wiktionary translation tables label VARIETIES, not macrolanguages: Chinese
# entries are emitted under 'cmn' (Mandarin), 'yue' (Cantonese) and friends,
# never under 'zh'. This extractor matched table codes exactly, so a zh run
# would attach ~nothing while every counter still reconciled -- a silent
# starve of the root ladder's translation rung, and the language would look
# pivot-dependent when it isn't.
#
# Maps OUR language code -> the set of table codes that count as it.
# Everything not listed maps to itself.
#
# DECISION (7/28/26): Mandarin only for zh. Cantonese ('yue') is excluded --
# our zh lexeme corpus is predominantly Mandarin, so yue targets would largely
# fail to resolve, and an unresolved translation still occupies a root
# candidate slot. Revisit only with evidence from the zh resolve rate.
_TABLE_CODE_ALIASES: dict[str, frozenset[str]] = {
    "zh": frozenset({"zh", "cmn"}),
}


def _accepted_table_codes(code: str | None) -> frozenset[str]:
    """Table codes that count as our language `code`. Identity by default.

    code may be None -- Language.code is nullable for pre-existing dev rows
    that predate language codes (see app/models/generated_name.py). None maps
    to an empty set rather than {None}: a translation item's table code is
    always a string, so an unaliased None could never match anyway, and this
    keeps the function's return type honestly frozenset[str].
    """
    if code is None:
        return frozenset()
    return _TABLE_CODE_ALIASES.get(code, frozenset({code}))


def _table_code_of(tr: dict) -> str:
    """The translation item's language code, however it is spelled."""
    return str(tr.get("code") or tr.get("lang_code") or "")

def _norm_gloss(s: str) -> str:
    return normalize_text(s or "").strip()


def _dis1_argmax(raw: str) -> int | None:
    try:
        weights = [float(w) for w in raw.split()]
    except (ValueError, AttributeError):
        return None
    if not weights or max(weights) <= 0:
        return None
    return weights.index(max(weights)) + 1


def run(args: argparse.Namespace) -> None:
    with SessionLocal() as db:
        db.execute(text("SET lock_timeout = '30s'"))

        target_lang = db.scalars(
            select(Language).where(Language.code == args.target_language_code)
        ).first()
        if target_lang is None:
            raise SystemExit(f"No Language row with code={args.target_language_code!r}")
        source = db.scalars(select(Source).where(Source.slug == "kaikki")).first()
        if source is None:
            raise SystemExit("No 'kaikki' source row")

        code = target_lang.code
        accepted_codes = _accepted_table_codes(code)
        if accepted_codes != {code}:
            print(f"table-code aliases for {code}: {sorted(accepted_codes)}")

        # Target-language lexeme resolution map (canonical key).
        lex_of: dict[str, int] = {}
        for lid, norm in db.execute(
            select(Lexeme.id, Lexeme.normalized_lemma)
            .where(Lexeme.language_id == target_lang.id)
        ).yield_per(5000):
            lex_of.setdefault(norm, lid)

        c: Counter = Counter()
        rows: list[dict] = []
        seen: set[tuple[int, str]] = set()

        def queue(sense_id: int, tr: dict, attachment: str) -> None:
            word = str(tr.get("word") or "").strip()
            if not word:
                c["items_no_word"] += 1
                return
            norm = normalize_lemma(word, code)
            if not norm:
                c["items_empty_norm"] += 1
                return
            key = (sense_id, norm)
            if key in seen:
                c["items_deduped"] += 1
                return
            seen.add(key)
            c[f"attach_{attachment}"] += 1
            lex_id = lex_of.get(norm)
            c["resolved" if lex_id else "unresolved"] += 1
            rows.append(dict(
                sense_id=sense_id,
                language_id=target_lang.id,
                target_text=word[:300],
                target_normalized=norm[:300],
                target_lexeme_id=lex_id,
                roman=(str(tr.get("roman"))[:300] if tr.get("roman") else None),
                attachment=attachment,
                source_id=source.id,
            ))

        # ---- Channel 1: sense-level (visible English senses) ---------------
        for sense_id, raw_sense in db.execute(
            select(Sense.id, Sense.raw_sense)
            .join(Lexeme, Lexeme.id == Sense.lexeme_id)
            .where(
                Lexeme.language_id == 1,
                Sense.visibility_status == "visible",
                text("(senses.raw_sense::jsonb) ? 'translations'"),
            )
        ).yield_per(2000):
            for tr in raw_sense.get("translations") or []:
                tc = _table_code_of(tr)
                if tc not in accepted_codes:
                    continue
                c["items_seen"] += 1
                c[f"tablecode_{tc}"] += 1
                queue(sense_id, tr, "sense")

        # ---- Channel 2: entry-level, routed ---------------------------------
        for lexeme_id, raw_entry in db.execute(
            select(Lexeme.id, Lexeme.raw_entry).where(
                Lexeme.language_id == 1,
                text("(lexemes.raw_entry::jsonb) ? 'translations'"),
            )
        ).yield_per(500):
            entry_trs = [
                tr for tr in (raw_entry.get("translations") or [])
                if _table_code_of(tr) in accepted_codes
            ]
            if not entry_trs:
                continue
            # Visible stored senses of this lexeme, keyed by sense_index.
            visible_by_index: dict[int, int] = {
                si: sid for sid, si in db.execute(
                    select(Sense.id, Sense.sense_index).where(
                        Sense.lexeme_id == lexeme_id,
                        Sense.visibility_status == "visible",
                    )
                )
            }
            glosses_by_index: dict[int, list[str]] = {
                i: [_norm_gloss(g) for g in
                    (sd.get("glosses") or sd.get("raw_glosses") or [])]
                for i, sd in enumerate(raw_entry.get("senses") or [], start=1)
            }
            for tr in entry_trs:
                c["items_seen"] += 1
                c[f"tablecode_{_table_code_of(tr)}"] += 1
                idx = _dis1_argmax(tr.get("_dis1") or "")
                if idx is not None and idx in visible_by_index:
                    queue(visible_by_index[idx], tr, "dis1")
                    continue
                hint = _norm_gloss(tr.get("sense") or "")
                routed = False
                if hint:
                    for i, gl in glosses_by_index.items():
                        if i in visible_by_index and any(
                            hint == g or g.startswith(hint) or hint.startswith(g)
                            for g in gl if g
                        ):
                            queue(visible_by_index[i], tr, "hint")
                            routed = True
                            break
                if not routed:
                    c["items_unrouted_excluded"] += 1

        for k in ("items_seen", "attach_sense", "attach_dis1", "attach_hint",
                  "items_unrouted_excluded", "items_deduped", "items_no_word",
                  "resolved", "unresolved"):
            print(f"{k:.<33} {c.get(k, 0)}")
        for k in sorted(k for k in c if k.startswith("tablecode_")):
            print(f"{k:.<33} {c[k]}")
        print(f"rows queued ...................... {len(rows)}")
        print(f"distinct english senses .......... {len({r['sense_id'] for r in rows})}")

        if not args.apply:
            print("\nDRY RUN -- nothing written. Re-run with --apply to commit.")
            return

        for i in range(0, len(rows), args.commit_every):
            stmt = pg_insert(SenseTranslation).values(rows[i:i + args.commit_every])
            stmt = stmt.on_conflict_do_nothing(constraint="uq_sense_translations_link")
            db.execute(stmt)
            db.commit()
        print(f"\nApplied: {len(rows)} rows for target={code}.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target-language-code", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--commit-every", type=int, default=5000)
    run(ap.parse_args())


if __name__ == "__main__":
    main()