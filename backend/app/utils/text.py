import unicodedata


def normalize_text(value: str) -> str:
    """
    Return a consistent search-friendly representation.

    NFKC normalizes Unicode presentation differences.
    casefold() provides robust caseless matching.
    """
    return unicodedata.normalize(
        "NFKC",
        value,
    ).strip().casefold()


# Languages whose lemma JOIN KEYS need full diacritic folding: their synonym
# references carry PRECOMPOSED marks (Latin macrons: ē is one codepoint, no Mn
# to strip). Evidence: Latin join 23.35% -> 98.59% under full fold; applying
# full fold globally MANUFACTURES false joins (English tía -> tia collides).
# See IMPORT_PREP_FINDINGS.md gates 3-4.
_FULL_FOLD_LANG_CODES: frozenset[str] = frozenset({"la"})

# Languages whose lemma JOIN KEYS must keep combining marks. The opposite pole
# from _FULL_FOLD_LANG_CODES, and for the opposite reason.
#
# In Devanagari, marks are not decoration: virama (U+094D, Mn) forms conjuncts
# and several vowel signs are Mn. The global strip is therefore BOTH lossy and
# collision-manufacturing -- the tía->tia failure class, at structural scale:
#     क्रम (krama, "order")  -> करम
#     कर्म (karma, "deed")   -> करम   <-- distinct words, one key
# Hindi and Sanskrit additionally share tatsama vocabulary in the same script,
# so the collisions compound across the two languages.
#
# ⚠ EXPECTED POLICY, NOT YET MEASURED. Landed before import because the branch
# is inert until hi/sa rows exist (§0 constraint 5: a key change after storage
# is update-or-collapse, before storage is free). Stage 6's B3 probe confirms
# the join rate; if it favors the global strip after all, remove these codes
# BEFORE importing and nothing else changes.
_NO_MARK_STRIP_LANG_CODES: frozenset[str] = frozenset({"hi", "sa"})


def _strip_marks(value: str) -> str:
    """Drop nonspacing combining marks (Unicode category Mn)."""
    return "".join(
        ch for ch in value if unicodedata.category(ch) != "Mn"
    )


def normalize_lemma(value: str, lang_code: str | None = None) -> str:
    """
    THE canonical lemma join key. Every producer of Lexeme.normalized_lemma
    and SenseRelation.target_normalized, and every fresh value compared
    against them, MUST use this function.

    Global policy: NFKC + casefold + strip combining marks (Mn). It repairs the
    reference side (Arabic harakat 0.7%->88%, Russian stress marks 12%->86%)
    while changing English joins by exactly zero refs (P1 == P2 == 98.57%).

    ⟲ REVISED: an earlier note here claimed headwords are Mn-free. They are
    not, and scanning `word` fields cannot establish that they are — two
    distinct mechanisms manufacture Mn downstream of the raw headword:
      1. casefold() PRODUCES marks (U+0130 'İ' -> 'i' + U+0307).
      2. NFKC decomposes certain composition-EXCLUDED precomposed letters
         (e.g. U+01F0 'ǰ' -> 'j' + U+030C) and never recomposes them, even
         with no language-specific fold involved. This applies globally, to
         any language, not just the Latin full-fold branch.
    Eight English lexemes carried Mn in their stored key for these reasons
    (3 via #1, 5 via #2); all were Tier A/B (hidden), so no embedded/visible
    search result was ever affected. Backfilled — see normkey_backfill.py.
    Watch item for future languages with composition-excluded diacritics
    (checked: none flagged yet in la/ru/ja/ar/en).

    Latin only: additionally NFD-decompose so precomposed macrons split into
    base + Mn, strip, then NFC-recompose (23%->98.6%).

    ⟲ REVISED (4): the policy now has THREE tiers, not two, because "strip
    combining marks" is right for some scripts and destructive for others:
      * _FULL_FOLD_LANG_CODES  (la)     -- decompose, strip, recompose
      * global default         (most)   -- NFKC + casefold + strip Mn
      * _NO_MARK_STRIP_LANG_CODES (hi, sa) -- NFKC + casefold only
    The sets are disjoint and full-fold is tested first; a code in both would
    silently take the full-fold path, which for a mark-bearing script would be
    the worst of the three. Keep them disjoint.

    Note this is a JOIN-KEY policy and is independent of prune_taxonomy rule 7,
    which decides whether a mark-bearing lemma may EXIST at all. Devanagari
    needed both: rule 7 governs the row, this governs the key.
    

    ⟲ REVISED (3): a key-policy change can MERGE rows, not just change values.
    The canonical key folds distinct raw references onto one key (Wiktionary
    carries 'ʔayʔaǰuθəm' and 'ʔayʔajuθəm' as separate entries; both land on
    'ʔayʔajuθəm'), and uq_sense_relations_edge is defined on that key — so a
    bare UPDATE raises UniqueViolation. Any future normalization change must
    classify drifted rows as update-or-collapse before writing. Collapse is
    lossless: expansion.py reads target_normalized alone, so two rows with one
    key ARE one edge. See normkey_backfill.py.
    """
    base = unicodedata.normalize("NFKC", value).strip().casefold()
    if lang_code in _FULL_FOLD_LANG_CODES:
        decomposed = unicodedata.normalize("NFD", base)
        return unicodedata.normalize("NFC", _strip_marks(decomposed))
    if lang_code in _NO_MARK_STRIP_LANG_CODES:
        # NFKC + casefold only. Marks are orthography here; stripping them
        # collapses distinct words onto one key (see the set's comment).
        return base
    return _strip_marks(base)