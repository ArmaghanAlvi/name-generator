from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.semantic import Sense

import unicodedata
from app.utils.languages import LANGUAGE_SCRIPTS

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
    # A triliteral / verbal ROOT is a morphological abstraction, never a name
    # candidate -- it belongs with the affix family. Measured Stage 6 B4:
    # he 438 · sa 2,323 · ar 1 · ja 5 · ko present, and ALL of them already
    # land Tier A, so this addition changes rule attribution, not tier:
    # census drift is zero (verified by the `root` blast-radius query).
    # LOAD-BEARING FOR HEBREW: he roots are written with maqaf (ר־ו־ץ), so
    # once rule 7 admits maqaf (_ORTHOGRAPHIC_PUNCT_CHARS) they would fall
    # through to Tier C without this line.
    "root",
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

# --- Language-conditioned policy (added for the 15-language batch) ---------
#
# Rule 7 (the isalpha gate) admits only L* categories plus _ALLOWED_LEMMA_CHARS.
# That is correct for scripts where a combining mark is a coding artifact, and
# WRONG for scripts where marks are ordinary spelling: Python's isalpha() is
# False for Mc (Devanagari matras) and Mn (virama, niqqud), so `किताब` and
# `अग्नि` were classified Tier A — a hard drop of ordinary Hindi/Sanskrit.
#
# Scoped to scripts NO currently-imported language uses, so existing behavior
# is unchanged by construction. Arabic script is deliberately EXCLUDED: `fa`
# needs it, but `ar` is already imported and shares the script, so that change
# is a measured decision gated on the Persian B1b probe, not a free extension.
_MARK_BEARING_SCRIPTS: frozenset[str] = frozenset({"Deva", "Hebr"})
# ⟲ Stage 6 B2 measured the Hebr entry as INERT: he headwords carry Mn on
# 0.10% of rows (niqqud absent, the Arabic pattern). RETAINED as free
# insurance against a future vocalized source; recorded as measured
# unnecessary rather than removed.

# ---------------------------------------------------------------------------
# Rule 7's language-scoped relaxations.
#
# Both sets below are scoped by LANGUAGE, never by SCRIPT: `ar` shares the
# Arabic script with `fa` and `he`-adjacent sources exist, and ar/ja/la/ru/en
# are ALREADY IMPORTED -- a script-scoped relaxation would re-tier stored rows
# (⟲ REVISED (3): update-or-collapse). Language scoping keeps every stored row
# byte-identical.
#
# Characters are listed EXPLICITLY, never by Unicode category. Admitting all
# of category Po would admit every period and comma; admitting all of Cf would
# admit invisible source contamination (see the sa ZWSP note in findings 6.10).
# ---------------------------------------------------------------------------

# Languages whose orthography uses FORMAT characters (Cf). Persian ZWNJ
# (U+200C) is a spelling device -- it separates morphemes INSIDE a written
# word -- so rule 7 must admit it or ordinary Persian compounds and verb
# forms are hard-dropped. Measured Stage 6 B1b: 926 of fa's 934 rule-7 drops
# are ordinary words (biology, Sunday, potato, democracy, girlfriend).
# `sa` is deliberately NOT here: its 15 rule-7 drops carry a TRAILING U+200B
# (ZERO WIDTH SPACE) which is source CONTAMINATION, not orthography, and
# admitting it without also stripping it from the join key would manufacture
# orphan lexemes (findings 6.10).
_CF_TOLERANT_LANG_CODES: frozenset[str] = frozenset({"fa"})
_ORTHOGRAPHIC_FORMAT_CHARS: frozenset[str] = frozenset({"\u200c", "\u200d"})

# Languages whose orthography uses PUNCTUATION characters as letters or as a
# hyphen. Hebrew: maqaf (U+05BE, Pd) IS the hyphen -- ASCII '-' is already in
# _ALLOWED_LEMMA_CHARS, so excluding maqaf was an inconsistency, not a policy.
# Geresh (U+05F3) marks foreign consonants (ג׳=/dʒ/ צ׳=/tʃ/ ז׳=/ʒ/); gershayim
# (U+05F4) marks acronyms. Measured Stage 6: 312 senses first-matched rule 7
# on these, all ordinary content (cappuccino, gel, jihad, jargon, wolf-fish);
# character split maqaf 61.0% / gershayim 22.5% / geresh 16.5%.
# ⚠ REQUIRES `root` in TIER_A_POS: he triliteral roots are written with maqaf
# (ר־ו־ץ), and without that POS entry they fall through to Tier C.
_ORTHOGRAPHIC_PUNCT_LANG_CODES: frozenset[str] = frozenset({"he"})
_ORTHOGRAPHIC_PUNCT_CHARS: frozenset[str] = frozenset({
    "\u05be",   # HEBREW PUNCTUATION MAQAF      (Pd) -- the hyphen
    "\u05f3",   # HEBREW PUNCTUATION GERESH     (Po) -- foreign consonants
    "\u05f4",   # HEBREW PUNCTUATION GERSHAYIM  (Po) -- acronyms
})


def _extra_lemma_chars(lang_code: str | None) -> frozenset[str]:
    """Characters that are ORTHOGRAPHY in this language, not junk.

    Empty for every language that predates the 15-language batch, so rule 7
    is byte-identical for en/la/ru/ja/ar.
    """
    if not lang_code:
        return frozenset()
    extra: set[str] = set()
    if lang_code in _CF_TOLERANT_LANG_CODES:
        extra |= _ORTHOGRAPHIC_FORMAT_CHARS
    if lang_code in _ORTHOGRAPHIC_PUNCT_LANG_CODES:
        extra |= _ORTHOGRAPHIC_PUNCT_CHARS
    return frozenset(extra)

# Categories that count as orthography in the scripts above:
#   Mn = nonspacing (virama, niqqud, anusvara)
#   Mc = spacing combining (Devanagari matras — the majority of Hindi words)
_ORTHOGRAPHIC_MARK_CATEGORIES: frozenset[str] = frozenset({"Mn", "Mc"})

# Rule 12 (leading-capital -> Tier B) assumes only proper nouns are
# capitalized. German capitalizes EVERY common noun, so the backstop would
# hide the language's entire name-candidate corpus. Exempt it.
#
# Losing the backstop for these languages means proper nouns misfiled under
# pos="noun" are no longer caught — accepted deliberately: rule 9
# (TIER_B_POS: name, num) still catches correctly-tagged proper nouns, and the
# alternative destroys the language.
#
# ⚠ STANDING CHECK: this set is a claim about a language list that grows.
# Re-verify against LANGUAGE_SCRIPTS at every onboarding, not against comments.
_CAPITALIZES_COMMON_NOUNS: frozenset[str] = frozenset({"de"})

# Unicode character-name prefixes for scripts whose single letters are never
# name candidates (they're letters/symbols, not words). A length-1 lemma in
# any of these is Tier A; single characters in other scripts (CJK, Arabic,
# Hebrew, Devanagari, Hangul, ...) are real words and fall through untouched.
#
# Rule 8 drops a LONE Latin/Cyrillic/Greek letter.
# ⟲ MEASURED, no longer deferred. Modern Greek (`el`) IS one of the 20 planned
# languages and is imported in the 15-language batch, so the original comment's
# revisit condition is met. Stage 6 B1 measured the cost: rule 8 fires on 24 of
# el's 112,818 senses (0.02%), and the population is letter-name entries.
# DECISION: RETAINED UNCHANGED. Removing "GREEK" would promote lone Greek
# letters in ENGLISH entries to Tier C, re-tiering stored English rows and
# breaking the byte-identity anchor, to recover 24 Greek senses. The trade is
# not close. Closes appendix T3 as an explicit decision.
# Re-verified at language #21 (`is`, Latn): rule 8 fires 4/32,797 senses
# (0.01%). Same population class (letter-name entries), no new script in
# _WESTERN_LETTER_SCRIPTS required. The list is now 21 languages, not 20 —
# re-verify against LANGUAGE_SCRIPTS at each future onboarding, not this count.
_WESTERN_LETTER_SCRIPTS = ("LATIN", "CYRILLIC", "GREEK")


def _lemma_chars_ok(
    lem: str,
    allow_marks: bool,
    extra_chars: frozenset[str] = frozenset(),
) -> bool:
    """Rule 7's character gate.

    allow_marks=False with an EMPTY extra_chars reproduces the original
    expression EXACTLY, so every caller that passes no language is
    byte-identical to pre-batch behavior.

    allow_marks=True additionally permits Mn/Mc. extra_chars additionally
    permits an explicit, language-scoped set of orthographic non-letters
    (Persian ZWNJ; Hebrew maqaf/geresh/gershayim). Either relaxation still
    requires at least one real letter -- otherwise a lemma of pure marks or
    pure punctuation would sail through rules 7-12 into Tier C.
    """
    if not allow_marks and not extra_chars:
        return all(
            ch.isalpha() or ch in _ALLOWED_LEMMA_CHARS for ch in lem
        )
    if not any(ch.isalpha() for ch in lem):
        return False
    return all(
        ch.isalpha()
        or ch in _ALLOWED_LEMMA_CHARS
        or ch in extra_chars
        or (allow_marks
            and unicodedata.category(ch) in _ORTHOGRAPHIC_MARK_CATEGORIES)
        for ch in lem
    )


def _marks_are_orthographic(lang_code: str | None) -> bool:
    """True when this language's script spells with combining marks."""
    if not lang_code:
        return False
    return LANGUAGE_SCRIPTS.get(lang_code) in _MARK_BEARING_SCRIPTS


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

def classify(
    pos: str,
    tags: Iterable[str],
    lemma: str,
    definition: str,
    lang_code: str | None = None,
) -> Tier:
    """
    Context-free tier for one sense, from raw fields only (no DB, no ORM), so
    it runs identically on a fetched Sense and on raw Kaikki JSON at import.

    lang_code is optional and conditions two rules only (7 and 12). It is a
    language CODE, never a DB object, so the no-DB property is preserved.
    Omitting it reproduces pre-15-batch behavior exactly — every rule falls
    back to its original expression — so existing callers are unaffected.

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
    defn = (definition or "").strip()

    if len(defn) < 3:        # 1. empty/short def
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
    if not _lemma_chars_ok(
        lem,
        _marks_are_orthographic(lang_code),
        _extra_lemma_chars(lang_code),
    ):
        return Tier.A                              # 7. dotted/coded (Det., S.F.X.)
    if _is_western_single_letter(lem):             # 8. lone Latin/Cyrillic/Greek letter
        return Tier.A                              #    ("a","b","c" — never a name)

    if pos_n in TIER_B_POS:                         # 9. proper nouns, numerals
        return Tier.B
    if tag_set & TIER_B_TAGS:                       # 10. registers, pluralia
        return Tier.B
    if " " in lem:                                  # 11. multiword noun/verb
        return Tier.B
    if (
        lang_code not in _CAPITALIZES_COMMON_NOUNS
        and lem[:1].isupper()
        and not lem.isupper()
    ):
        return Tier.B                               # 12. proper-noun backstop

    return Tier.C                                   # 13. real name candidate


def classify_sense(sense: "Sense", lang_code: str | None = None) -> Tier:
    """ORM adapter: pull the four raw fields off a Sense and classify.

    lang_code must be supplied by the caller — Sense.lexeme carries only
    language_id, and resolving it to a code here would mean a DB lookup per
    sense, breaking the no-DB property. Callers that iterate build the id->code
    map once (see scripts/prune/classify_db_census.py, sense_embeddings.py).
    """
    lexeme = sense.lexeme
    return classify(
        pos=(lexeme.part_of_speech or ""),
        tags=(sense.raw_tags or []),
        lemma=(lexeme.lemma or ""),
        definition=(sense.definition or ""),
        lang_code=lang_code,
    )


def sole_alt_trigger(
    pos: str,
    tags: Iterable[str],
    lemma: str,
    definition: str,
    lang_code: str | None = None,
) -> bool:
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
    if classify(pos, tag_set, lemma, definition, lang_code) is not Tier.A:
        return False
    return classify(
        pos, tag_set - _ALT_TAGS, lemma, definition, lang_code
    ) is not Tier.A

# ⟲ SUPERSEDED (15-language batch). This note previously claimed the
# capitalization backstop was "safe for all 20 planned languages: none
# capitalizes common nouns (German-style)." German ("de": "Latn") was already
# in LANGUAGE_SCRIPTS when that was written. Measured 7/27/26: every German
# noun classified Tier B — hidden and never embedded.
#
# The exemption now lives in _CAPITALIZES_COMMON_NOUNS above, conditioned on
# lang_code. Caseless scripts (Arabic, Hebrew, Devanagari, CJK) still make the
# rule inert without needing an entry.
#
# GENERALIZABLE LESSON: a comment asserting scope-safety over "the 20 planned
# languages" is a claim about a list that changes underneath it. Such claims
# must be re-verified against LANGUAGE_SCRIPTS at each onboarding.
#
# Re-verified at language #21 (`is`, Latn, capitalizes sentence-initial and
# proper nouns only — not the German pattern). Measured: rule 12 fires
# 156/32,797 senses (0.48%), all POS=noun, all nationality/demonym nouns
# (Pakistani, Nepali, Þjóðverji). No _CAPITALIZES_COMMON_NOUNS entry needed.
# The list is now 21 languages — re-verify at each future onboarding.