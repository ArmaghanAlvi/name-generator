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