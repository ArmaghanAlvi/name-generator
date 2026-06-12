from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


CONFIDENCE_VALUES = {
    "high",
    "medium",
    "low",
}

REVIEW_STATUS_VALUES = {
    "unreviewed",
    "reviewed",
    "rejected",
}

CONCEPT_STATUS_VALUES = {
    "active",
    "draft",
    "retired",
}

RELATIONSHIP_TYPE_VALUES = {
    "synonym",
    "near_synonym",
    "symbolic",
    "associated",
    "broader",
    "narrower",
    "contrast",
}


class CatalogValidationError(ValueError):
    """Raised when a curated CSV file contains an invalid row."""


def require(
    row: dict[str, str],
    key: str,
    *,
    file: Path,
    line: int,
) -> str:
    value = row.get(key, "").strip()

    if not value:
        raise CatalogValidationError(
            f"{file.name}:{line}: "
            f"required field '{key}' is empty"
        )

    return value


def optional(
    row: dict[str, str],
    key: str,
) -> str | None:
    value = row.get(key, "").strip()
    return value or None


def parse_bool(
    value: str,
    *,
    file: Path,
    line: int,
    field: str,
) -> bool:
    normalized = value.strip().casefold()

    if normalized in {"true", "1", "yes"}:
        return True

    if normalized in {"false", "0", "no"}:
        return False

    raise CatalogValidationError(
        f"{file.name}:{line}: "
        f"field '{field}' must be true or false"
    )


def parse_weight(
    value: str,
    *,
    file: Path,
    line: int,
) -> float:
    try:
        weight = float(value)
    except ValueError as exc:
        raise CatalogValidationError(
            f"{file.name}:{line}: weight must be a number"
        ) from exc

    if not 0 <= weight <= 1:
        raise CatalogValidationError(
            f"{file.name}:{line}: "
            "weight must be between 0 and 1"
        )

    return weight


def require_choice(
    value: str,
    allowed: set[str],
    *,
    file: Path,
    line: int,
    field: str,
) -> str:
    normalized = value.strip().casefold()

    if normalized not in allowed:
        choices = ", ".join(sorted(allowed))

        raise CatalogValidationError(
            f"{file.name}:{line}: "
            f"field '{field}' must be one of: {choices}"
        )

    return normalized


def ensure_unique_rows(
    rows: Iterable[tuple[int, dict[str, str]]],
    *,
    file: Path,
    key_fields: tuple[str, ...],
) -> None:
    seen: dict[tuple[str, ...], int] = {}

    for line, row in rows:
        key = tuple(
            row.get(field, "").strip().casefold()
            for field in key_fields
        )

        if key in seen:
            joined = ", ".join(key_fields)

            raise CatalogValidationError(
                f"{file.name}:{line}: "
                f"duplicate row key for ({joined}); "
                f"first seen on line {seen[key]}"
            )

        seen[key] = line