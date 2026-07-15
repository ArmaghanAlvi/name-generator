from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.semantic import Sense

import unicodedata


class Tier(str, Enum):
    A = "A"  # hard-drop: never belongs in the DB, in any language
    B = "B"  # keep row, never embed, hidden from the dropdown
    C = "C"  # keep and embed: a real single-word name candidate


# --- Tier A: hard-drop parts of speech ---
TIER_A_POS: frozenset[str] = frozenset({
    # function words
    "article", "prep", "pron", "conj", "det", "particle", "contraction", "postp",
    # affixes / combining forms
    "prefix", "suffix", "infix", "interfix", "circumfix",
    # standalone glyphs
    "symbol", "character", "punct",
    # multiword *expressions* (multiword nouns are Tier B, via the shape rule)
    "phrase", "prep_phrase", "adv_phrase", "proverb",
    # expressive noises, no concept content
    "intj",
    # cross-reference entry shapes, not words (Japanese Kaikki; gate 10 in
    # IMPORT_PREP_FINDINGS.md — 152 romanization senses leaked to Tier C)
    "romanization", "soft-redirect",
})

# --- Tier A: hard-drop tags (sense-level; ride on any POS) ---
TIER_A_TAGS: frozenset[str] = frozenset({
    "form-of", "alt-of", "alternative", "clipping", "ellipsis",
    "misspelling", "pronunciation-spelling", "morpheme",
    "abbreviation", "initialism", "acronym",
    "vulgar", "derogatory",
})

# --- Tier B: keep, don't embed, hide from dropdown ---
TIER_B_POS: frozenset[str] = frozenset({"name", "num"})

TIER_B_TAGS: frozenset[str] = frozenset({
    "slang", "obsolete", "archaic", "dated", "historical",
    "nonstandard", "dialectal",
    # pluralia tantum — kept OUT of C to hold the pre-refactor embed set
    # stable (see breakdown note); flag if you'd rather drop or embed these.
    "plural-only", "in-plural",
})

_ALLOWED_LEMMA_CHARS = "-' "  # besides letters: hyphen, apostrophe, space

_ALT_TAGS = frozenset({"alt-of", "alternative"})

# Unicode character-name prefixes for scripts whose single letters are never
# name candidates (they're letters/symbols, not words). A length-1 lemma in
# any of these is Tier A; single characters in other scripts (CJK, Arabic,
# Hebrew, Devanagari, Hangul, ...) are real words and fall through untouched.
# NOTE: Greek is included because it is NOT one of the 20 planned languages —
# a lone Greek letter here is a math/physics symbol. If Greek is ever added
# as a language, revisit this (see PRUNING.md).
_WESTERN_LETTER_SCRIPTS = ("LATIN", "CYRILLIC", "GREEK")


def _is_western_single_letter(lem: str) -> bool:
    """True iff lem is exactly one character and that character is a Latin,
    Cyrillic, or Greek letter (including accented Latin like 'é')."""
    if len(lem) != 1:
        return False
    try:
        name = unicodedata.name(lem)
    except ValueError:          # unnamed char (control, private-use, etc.)
        return False
    return name.split(" ", 1)[0] in _WESTERN_LETTER_SCRIPTS

def classify(pos: str, tags: Iterable[str], lemma: str, definition: str) -> Tier:
    """
    Context-free tier for one sense, from raw fields only (no DB, no ORM), so
    it runs identically on a fetched Sense and on raw Kaikki JSON at import.

    NOTE: the alt-of ORPHAN RESCUE (keep a purely-alt lexeme whose target is
    absent) is NOT applied here — it needs global knowledge of which lemmas
    exist, so the caller (purge SQL / import pass) layers it on. Here, every
    alt-of/alternative sense is Tier A.
    """
    pos_n = (pos or "").strip().lower()
    tag_set = {str(t).strip().lower() for t in (tags or [])}
    # NFC first: composition-encoding of the source must not affect tiering
    # (gate 1 — proven zero tier changes on all five languages; insurance only).
    lem = unicodedata.normalize("NFC", (lemma or "").strip())

    if len((definition or "").strip()) < 3:        # 1. empty/short def
        return Tier.A
    if not lem:                                    # 2. empty lemma
        return Tier.A
    if pos_n in TIER_A_POS:                         # 3. hard-drop POS
        return Tier.A
    if tag_set & TIER_A_TAGS:                       # 4. hard-drop tags
        return Tier.A
    if any(ch.isdigit() for ch in lem):            # 5. coded lemma (s620, -4j)
        return Tier.A
    if lem.startswith("-") or lem.endswith("-"):   # 6. hyphen-edge affix
        return Tier.A
    if not all(ch.isalpha() or ch in _ALLOWED_LEMMA_CHARS for ch in lem):
        return Tier.A                              # 7. dotted/coded (Det., S.F.X.)
    if _is_western_single_letter(lem):             # 8. lone Latin/Cyrillic/Greek letter
        return Tier.A                              #    ("a","b","c" — never a name)

    if pos_n in TIER_B_POS:                         # 9. proper nouns, numerals
        return Tier.B
    if tag_set & TIER_B_TAGS:                       # 10. registers, pluralia
        return Tier.B
    if " " in lem:                                  # 11. multiword noun/verb
        return Tier.B
    if lem[:1].isupper() and not lem.isupper():     # 12. proper-noun backstop
        return Tier.B                               #     (English-specific; Stage 6)

    return Tier.C                                   # 13. real name candidate


def classify_sense(sense: "Sense") -> Tier:
    """ORM adapter: pull the four raw fields off a Sense and classify."""
    lexeme = sense.lexeme
    return classify(
        pos=(lexeme.part_of_speech or ""),
        tags=(sense.raw_tags or []),
        lemma=(lexeme.lemma or ""),
        definition=(sense.definition or ""),
    )


def sole_alt_trigger(pos: str, tags: Iterable[str], lemma: str, definition: str) -> bool:
    """
    True when a sense is Tier A *only because* of alt-of/alternative tags —
    i.e. stripping those tags would make it non-A. The importer keeps such
    senses as hidden 'provisional' rows so a post-import pass can apply the
    orphan rescue (keep if target absent, delete if target present), which
    can't be decided mid-import since the target may appear later in the file.
    """
    tag_set = {str(t).strip().lower() for t in (tags or [])}
    if not (tag_set & _ALT_TAGS):
        return False
    if classify(pos, tag_set, lemma, definition) is not Tier.A:
        return False
    return classify(pos, tag_set - _ALT_TAGS, lemma, definition) is not Tier.A

# NOTE on the capitalization backstop (rule 11 in classify): it treats a
# leading-capital lemma as proper-noun-ish (Tier B). This is safe for all 20
# planned languages: none capitalizes common nouns (German-style), and the
# caseless scripts (Arabic, Hebrew, Devanagari, CJK) make the rule inert.
# Revisit only if a common-noun-capitalizing language is ever added.