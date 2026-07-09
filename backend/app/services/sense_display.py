from __future__ import annotations

from dataclasses import dataclass

from app.models.semantic import Sense, SenseAdminOverride
from app.utils.text import normalize_text


# Max header segments kept in a group path. Observed max depth is 4 glosses
# (3 segments), so this is a safety cap, not an active filter.
MAX_GROUP_SEGMENTS = 3

# A header must be at least this long (normalized) before the prefix-redundancy
# rule is allowed to drop it. Guards against a short header like "Of:" matching
# an unrelated definition by coincidence.
MIN_REDUNDANT_HEADER_LENGTH = 6

GROUP_SEPARATOR = " > "


@dataclass(frozen=True)
class SenseDisplay:
    """
    Presentation-layer view of a sense's gloss structure.

    `definition` is the most specific gloss (what the user reads).
    `group_path` is the outer category header(s), outermost first, with
    redundant headers removed. Empty for the overwhelming majority of senses.

    Derived at read time. The stored `Sense.definition` column, which backs
    `source_locator` and the import contract, is never touched.
    """

    definition: str
    group_path: tuple[str, ...]

    @property
    def group_label(self) -> str | None:
        if not self.group_path:
            return None
        return GROUP_SEPARATOR.join(self.group_path)


def _clean_glosses(raw_glosses: object) -> list[str]:
    """Defensive: raw_glosses is JSON from an external dump."""
    if not isinstance(raw_glosses, list):
        return []

    return [
        gloss.strip()
        for gloss in raw_glosses
        if isinstance(gloss, str) and gloss.strip()
    ]


def _normalize_header(header: str) -> str:
    return normalize_text(header).rstrip(":").strip()


def _is_redundant_header(header: str, definition: str) -> bool:
    """
    True when the definition already restates the header, e.g.
        header     = "The act of drawing:"
        definition = "The act of drawing a gun from a holster, etc."
    """
    normalized_header = _normalize_header(header)

    if len(normalized_header) < MIN_REDUNDANT_HEADER_LENGTH:
        return False

    normalized_definition = normalize_text(definition)

    return (
        normalized_definition[: len(normalized_header)] == normalized_header
    )


def sense_display_for(
    sense: Sense,
    override: SenseAdminOverride | None = None,
) -> SenseDisplay:
    """
    Derive the text shown for a sense in the selection dropdown.

    Precedence:
      1. An admin definition_override replaces everything (group dropped —
         the admin's text is final and self-contained).
      2. Otherwise the last gloss is the definition, earlier glosses become
         the group path, and redundant headers are dropped.
      3. If raw_glosses is empty or malformed, fall back to the stored
         definition column.
    """
    if override is not None and override.definition_override:
        return SenseDisplay(
            definition=override.definition_override,
            group_path=(),
        )

    glosses = _clean_glosses(sense.raw_glosses)

    if not glosses:
        return SenseDisplay(
            definition=sense.definition or "",
            group_path=(),
        )

    definition = glosses[-1]

    group_path = tuple(
        header
        for header in glosses[:-1][:MAX_GROUP_SEGMENTS]
        if not _is_redundant_header(header, definition)
    )

    return SenseDisplay(
        definition=definition,
        group_path=group_path,
    )