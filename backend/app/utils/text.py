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
    return _strip_marks(base)