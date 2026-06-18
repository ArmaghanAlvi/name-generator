from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.extractors.export_reviewed_oewn_yellow import (
    export_reviewed_oewn_yellow,
)
from app.review.export_reviewed import (
    export_review_db_to_candidate_csvs,
)

import sqlite3

import pandas as pd
import streamlit as st


DB_PATH = Path("data/review/oewn-2025.sqlite")

TABLES = {
    "Concepts": "review_concepts",
    "Words": "review_words",
    "Word senses": "review_word_senses",
    "Relationships": "review_relationships",
    "Mappings": "review_mappings",
}

STATUS_DRILLDOWN_TABLES = {
    "Concepts": {
        "table": "review_concepts",
        "columns": [
            "id",
            "slug",
            "label",
            "description",
            "domain",
            "status",
            "concept_type",
            "is_public",
            "external_source_slug",
            "external_concept_id",
            "review_status",
            "decision",
            "target_concept_slug",
            "notes",
            "priority",
            "review_reason",
        ],
        "order_by": "slug",
    },
    "Words": {
        "table": "review_words",
        "columns": [
            "id",
            "language_code",
            "text",
            "transliteration",
            "part_of_speech",
            "external_entry_id",
            "source_slug",
            "review_status",
            "notes",
            "priority",
            "review_reason",
        ],
        "order_by": "text",
    },
    "Word senses": {
        "table": "review_word_senses",
        "columns": [
            "id",
            "language_code",
            "word_text",
            "part_of_speech",
            "concept_slug",
            "gloss",
            "is_primary",
            "equivalence_type",
            "sense_rank",
            "external_sense_id",
            "external_synset_id",
            "source_slug",
            "source_locator",
            "confidence",
            "review_status",
            "notes",
            "priority",
            "review_reason",
        ],
        "order_by": "concept_slug, word_text",
    },
    "Relationships": {
        "table": "review_relationships",
        "columns": [
            "id",
            "source_concept_slug",
            "target_concept_slug",
            "relationship_type",
            "weight",
            "source_slug",
            "source_locator",
            "confidence",
            "review_status",
            "notes",
            "priority",
            "review_reason",
        ],
        "order_by": "source_concept_slug, target_concept_slug",
    },
    "Mappings": {
        "table": "review_mappings",
        "columns": [
            "id",
            "source_concept_slug",
            "target_concept_slug",
            "mapping_type",
            "weight",
            "source_slug",
            "source_locator",
            "confidence",
            "review_status",
            "notes",
            "priority",
            "review_reason",
        ],
        "order_by": "source_concept_slug, target_concept_slug",
    },
}

VALID_STATUSES = [
    "pending_review",
    "reviewed",
    "rejected",
    "deferred",
    "needs_edit",
    "duplicate",
]

CONCEPT_GROUP_EXPR = """
CASE
    WHEN instr(label, '/') > 0 THEN lower(trim(substr(label, 1, instr(label, '/') - 1)))
    ELSE lower(trim(label))
END
"""

CONCEPT_GROUP_EXPR_WITH_ALIAS = """
CASE
    WHEN instr(concepts.label, '/') > 0 THEN lower(trim(substr(concepts.label, 1, instr(concepts.label, '/') - 1)))
    ELSE lower(trim(concepts.label))
END
"""

REVIEW_GUIDES = {
    "Progress": """
Use this page to check the overall state of the review workspace.

**What to look for**
- Large numbers of `pending_review` rows mean there is still review work left.
- `needs_edit` rows should be fixed before export.
- `deferred`, `duplicate`, and `rejected` rows will not be exported.
- Only `reviewed` rows are exported into curated CSVs.

**Correct**
- Counts gradually move from `pending_review` to `reviewed`, `rejected`, or `deferred`.
- You export only after the important candidate groups have enough reviewed rows.

**Incorrect**
- Exporting while many important word senses are still `pending_review`.
- Ignoring `needs_edit` rows that may represent broken slugs, missing fields, or bad relationships.
""",
    "Concepts": """
Concepts are the searchable meaning nodes. In the new yellow-card model, every important searchable word/sense should have its own concept.

**Accept when**
- The concept is useful as a searchable yellow-card meaning.
- The label and description clearly describe one meaning.
- The concept is not merely a hidden expansion word.
- `is_public = true` if users should be able to search it.
- It is not a duplicate of an existing accepted concept.
- Accept concepts that represent one clear, searchable meaning. 

**Reject when**
- The concept is too technical, obscure, or not useful for name generation right now.
- The definition describes a measurement unit, instrument, chemical, scientific process, or unrelated technical object.
- The candidate is malformed or has a bad slug/label.

**Mark duplicate when**
- It is basically the same meaning as an existing accepted concept.
- Example: if `luminosity` is being treated as the same concept as `brightness`, mark it duplicate or defer instead of accepting both blindly.

**Correct**
- `brightness` is its own searchable concept.
- `radiance` is its own searchable concept.
- `liberty` is its own searchable concept.

**Incorrect**
- Accepting `brightness` only as a hidden child of `illumination`.
- Accepting many tiny technical variants that would clutter search results.
""",
    "Word senses": """
Word senses connect a word form to its exact concept. This is the most important review page.

**Accept when**
- The word points to its own exact meaning concept.
- The gloss matches the intended sense.
- The part of speech is correct.
- The source locator and external sense/synset data look valid.
- `equivalence_type` is correct.

**Reject when**
- The gloss is for the wrong sense.
- The word is attached to a broader or merely related concept.
- The word should only be related by expansion, not treated as the same meaning.
- The row is malformed or missing important source data.

**Correct**
- `brightness → brightness`
- `radiance → radiance`
- `liberty → liberty`
- `ocean → ocean`
- `light → illumination`

**Incorrect**
- `brightness → illumination`
- `radiance → illumination`
- `liberty → freedom`
- `ocean → sea`

Those incorrect examples should usually be represented in `Relationships`, not word senses.

**Equivalence type**
- Use `canonical` for the main word in its own language/concept.
- Use `direct_equivalent` for future literal translations in other languages.
- Use `near_equivalent`, `related`, or `symbolic` only when the word truly belongs as a secondary wording for the same concept.

**Sense rank**
- `sense_rank` chooses the best display word within one language for the same concept.
- It does not control expansion.
""",
    "Words": """
Words are lexical forms. They say that a word exists, but they do not decide meaning by themselves.

**Accept when**
- The spelling is correct.
- The language code is correct.
- The part of speech is correct.
- The word is suitable for yellow-card display.
- A reviewed word sense uses this word.

**Reject or defer when**
- The word is too obscure, technical, malformed, or not useful right now.
- The word is a proper noun, abbreviation, or phrase you do not want to support yet.
- The part of speech is missing or clearly wrong.

**Correct**
- `brightness`, noun
- `radiance`, noun
- `liberty`, noun
- `ocean`, noun

**Incorrect**
- A malformed word with underscores or extraction artifacts.
- A word whose only available sense is rejected.
""",
    "Relationships": """
Relationships control expansion. They connect equally valid searchable concepts.

**Accept when**
- Expanding from the source concept should show the target concept.
- The relationship type describes the connection accurately.
- The weight reflects how close the concepts are.
- The target concept is useful and searchable.

**Reject when**
- The relationship is too weak, technical, misleading, or not useful.
- Expanding would produce confusing results.
- The relationship connects unrelated senses.

**Correct**
- `illumination → brightness`
- `brightness → illumination`
- `illumination → radiance`
- `freedom → liberty`
- `liberty → freedom`
- `sea → ocean`
- `ocean → sea`

**Incorrect**
- Using word senses to represent similarity instead of relationships.
- Accepting a relationship just because OEWN extracted it, without checking if it helps the app.

**Weights**
- `0.95`: almost identical
- `0.85–0.90`: strongly related
- `0.65–0.75`: moderately related
- `0.40–0.60`: weak, symbolic, or contextual
- below `0.40`: usually defer or reject

**Bidirectional review**
- For synonyms and near-synonyms, usually use **Accept + create reverse relationship**.
- For broader/narrower relationships, be more careful with direction.
""",
    "Batch review": """
Batch review is for safe repeated decisions. Always preview rows before applying a batch action.

**Use batch accept when**
- The rule is conservative.
- The previewed rows are obviously correct.
- The rows are high-priority and consistent.

**Use batch defer/reject when**
- Rows are clearly technical, malformed, weak, or outside your current scope.
- Relationship weights are very low.
- Concepts are not useful for yellow-card search yet.

**Correct**
- Preview high-priority exact word senses, scan them, then batch accept only if they are clearly right.
- Preview weak relationships, scan them, then defer or reject.

**Incorrect**
- Batch accepting thousands of rows without looking at the preview.
- Batch accepting relationships just because they came from OEWN.
- Batch accepting word senses where the word is attached to a broader related concept instead of its exact concept.
""",
    "Export preview": """
Use this page before creating the next curated dataset version.

**What will export**
- Only rows with `review_status = reviewed`.
- `deferred`, `rejected`, `duplicate`, `needs_edit`, and `pending_review` rows are not exported.

**Before exporting**
- Check that important concepts have reviewed word senses.
- Check that useful expansion relationships are reviewed.
- Check that `needs_edit` rows are resolved or intentionally left out.
- Confirm that the reviewed counts look reasonable.

**Correct**
- Export a small reviewed batch.
- Dry-run import into the curated catalog.
- Run tests.
- Test frontend search behavior.
- Commit the new curated version separately.

**Incorrect**
- Exporting before reviewing word senses.
- Exporting with unresolved required data issues.
- Committing local SQLite review databases.
""",
}


def render_review_guide(page: str) -> None:
    guide = REVIEW_GUIDES.get(page)

    if guide is None:
        return

    with st.expander("How to review", expanded=True):
        st.markdown(guide)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def read_sql(
    conn: sqlite3.Connection,
    query: str,
    params: tuple = (),
) -> pd.DataFrame:
    return pd.read_sql_query(
        query,
        conn,
        params=params,
    )


def execute(
    conn: sqlite3.Connection,
    query: str,
    params: tuple = (),
) -> None:
    conn.execute(
        query,
        params,
    )
    conn.commit()


def progress_counts(
    conn: sqlite3.Connection,
    table: str,
) -> pd.DataFrame:
    return read_sql(
        conn,
        f"""
        SELECT review_status, COUNT(*) AS count
        FROM {table}
        GROUP BY review_status
        ORDER BY review_status
        """,
    )


def all_progress_counts(
    conn: sqlite3.Connection,
) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []

    for label, table in TABLES.items():
        frame = progress_counts(
            conn,
            table,
        )
        frame.insert(
            0,
            "table_name",
            label,
        )
        parts.append(frame)

    if not parts:
        return pd.DataFrame()

    return pd.concat(
        parts,
        ignore_index=True,
    )


def pending_concept_count(
    conn: sqlite3.Connection,
) -> int:
    result = read_sql(
        conn,
        """
        SELECT COUNT(*) AS count
        FROM review_concepts
        WHERE review_status = 'pending_review'
        """
    )

    if result.empty:
        return 0

    return int(result.iloc[0]["count"])


def concept_group_review_summary(
    conn: sqlite3.Connection,
) -> pd.DataFrame:
    return read_sql(
        conn,
        f"""
        WITH grouped AS (
            SELECT
                {CONCEPT_GROUP_EXPR} AS concept_group,
                COUNT(*) AS total_count,
                SUM(
                    CASE
                        WHEN review_status = 'pending_review' THEN 1
                        ELSE 0
                    END
                ) AS pending_count,
                SUM(
                    CASE
                        WHEN review_status = 'reviewed' THEN 1
                        ELSE 0
                    END
                ) AS reviewed_count,
                SUM(
                    CASE
                        WHEN review_status = 'rejected' THEN 1
                        ELSE 0
                    END
                ) AS rejected_count,
                SUM(
                    CASE
                        WHEN review_status = 'deferred' THEN 1
                        ELSE 0
                    END
                ) AS deferred_count,
                GROUP_CONCAT(slug, ', ') AS candidate_slugs
            FROM review_concepts
            WHERE label != ''
            GROUP BY concept_group
        )
        SELECT *
        FROM grouped
        ORDER BY
            CASE
                WHEN pending_count > 0 AND reviewed_count = 0 THEN 0
                ELSE 1
            END,
            concept_group
        """
    )


def unresolved_concept_group_count(
    conn: sqlite3.Connection,
) -> int:
    result = read_sql(
        conn,
        f"""
        WITH grouped AS (
            SELECT
                {CONCEPT_GROUP_EXPR} AS concept_group,
                SUM(
                    CASE
                        WHEN review_status = 'pending_review' THEN 1
                        ELSE 0
                    END
                ) AS pending_count,
                SUM(
                    CASE
                        WHEN review_status = 'reviewed' THEN 1
                        ELSE 0
                    END
                ) AS reviewed_count
            FROM review_concepts
            WHERE label != ''
            GROUP BY concept_group
        )
        SELECT COUNT(*) AS unresolved_count
        FROM grouped
        WHERE pending_count > 0
          AND reviewed_count = 0
        """
    )

    if result.empty:
        return 0

    return int(result.iloc[0]["unresolved_count"])


def unresolved_concept_groups(
    conn: sqlite3.Connection,
) -> pd.DataFrame:
    summary = concept_group_review_summary(conn)

    if summary.empty:
        return summary

    return summary[
        (summary["pending_count"] > 0)
        & (summary["reviewed_count"] == 0)
    ].reset_index(drop=True)


def status_filter_sidebar() -> tuple[str, int, str]:
    status = st.sidebar.selectbox(
        "Status",
        VALID_STATUSES,
        index=0,
    )
    limit = st.sidebar.slider(
        "Rows per page",
        min_value=5,
        max_value=100,
        value=25,
        step=5,
    )
    search = st.sidebar.text_input(
        "Search text",
        value="",
    ).strip()

    return status, limit, search


def render_status_drilldown(
    conn: sqlite3.Connection,
) -> None:
    drilldown = st.session_state.get("progress_drilldown")

    if drilldown is None:
        return

    table_label = drilldown["table_label"]
    status = drilldown["status"]

    st.divider()

    st.subheader(f"{status.replace('_', ' ').title()} {table_label}")

    col1, col2 = st.columns(
        [
            3,
            1,
        ]
    )

    with col1:
        search = st.text_input(
            "Search within this list",
            key="progress_drilldown_search",
        ).strip()

    with col2:
        if st.button("Close list"):
            st.session_state["progress_drilldown"] = None
            st.rerun()

    rows = load_status_drilldown(
        conn,
        table_label=table_label,
        status=status,
        search=search,
    )

    st.caption(f"{len(rows)} rows")

    if rows.empty:
        st.info("No rows match this filter.")
        return

    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
    )

    csv_data = rows.to_csv(
        index=False,
    ).encode("utf-8")

    st.download_button(
        label="Download this list as CSV",
        data=csv_data,
        file_name=(
            f"{table_label.lower().replace(' ', '_')}"
            f"_{status}.csv"
        ),
        mime="text/csv",
    )


def update_status(
    conn: sqlite3.Connection,
    table: str,
    row_id: int,
    status: str,
) -> None:
    execute(
        conn,
        f"""
        UPDATE {table}
        SET review_status = ?
        WHERE id = ?
        """,
        (
            status,
            row_id,
        ),
    )


def update_field(
    conn: sqlite3.Connection,
    table: str,
    row_id: int,
    field: str,
    value: str | None,
) -> None:
    allowed_fields = {
        "slug",
        "label",
        "description",
        "domain",
        "status",
        "concept_type",
        "is_public",
        "decision",
        "target_concept_slug",
        "notes",
        "concept_slug",
        "gloss",
        "equivalence_type",
        "sense_rank",
        "relationship_type",
        "weight",
        "confidence",
    }

    if field not in allowed_fields:
        raise ValueError(f"Unsafe field update: {field}")

    execute(
        conn,
        f"""
        UPDATE {table}
        SET {field} = ?
        WHERE id = ?
        """,
        (
            value or "",
            row_id,
        ),
    )


def batch_update_status(
    conn: sqlite3.Connection,
    table: str,
    ids: list[int],
    status: str,
) -> None:
    if not ids:
        return

    placeholders = ", ".join(
        "?"
        for _ in ids
    )

    execute(
        conn,
        f"""
        UPDATE {table}
        SET review_status = ?
        WHERE id IN ({placeholders})
        """,
        (
            status,
            *ids,
        ),
    )


def reject_all_pending_concepts(
    conn: sqlite3.Connection,
) -> int:
    cursor = conn.execute(
        """
        UPDATE review_concepts
        SET
            review_status = 'rejected',
            notes = CASE
                WHEN notes = '' THEN 'Rejected by bulk reject remaining pending concepts action.'
                ELSE notes || ' Rejected by bulk reject remaining pending concepts action.'
            END
        WHERE review_status = 'pending_review'
        """
    )
    conn.commit()

    return cursor.rowcount


def reject_all_pending_word_senses(
    conn: sqlite3.Connection,
) -> int:
    cursor = conn.execute(
        """
        UPDATE review_word_senses
        SET
            review_status = 'rejected',
            notes = CASE
                WHEN notes = '' THEN 'Rejected by bulk reject remaining pending word senses action.'
                ELSE notes || ' Rejected by bulk reject remaining pending word senses action.'
            END
        WHERE review_status = 'pending_review'
        """
    )
    conn.commit()

    return cursor.rowcount


def reject_relationships_with_unreviewed_concepts(
    conn: sqlite3.Connection,
) -> int:
    cursor = conn.execute(
        """
        UPDATE review_relationships
        SET
            review_status = 'rejected',
            notes = CASE
                WHEN notes = '' THEN
                    'Rejected because source or target concept was not reviewed.'
                ELSE
                    notes || ' Rejected because source or target concept was not reviewed.'
            END
        WHERE review_status = 'pending_review'
          AND id IN (
            SELECT relationships.id
            FROM review_relationships AS relationships
            LEFT JOIN review_concepts AS source_concepts
              ON relationships.source_concept_slug = source_concepts.slug
            LEFT JOIN review_concepts AS target_concepts
              ON relationships.target_concept_slug = target_concepts.slug
            WHERE relationships.review_status = 'pending_review'
              AND (
                  COALESCE(source_concepts.review_status, 'missing') != 'reviewed'
                  OR COALESCE(target_concepts.review_status, 'missing') != 'reviewed'
              )
          )
        """
    )
    conn.commit()

    return cursor.rowcount


def load_concepts(
    conn: sqlite3.Connection,
    *,
    status: str,
    limit: int,
    search: str,
) -> pd.DataFrame:
    params: list[str | int] = [
        status,
    ]

    where = "concepts.review_status = ?"

    if search:
        where += """
        AND (
            concepts.slug LIKE ?
            OR concepts.label LIKE ?
            OR concepts.description LIKE ?
            OR concepts.notes LIKE ?
        )
        """
        like = f"%{search}%"
        params.extend(
            [
                like,
                like,
                like,
                like,
            ]
        )

    params.append(limit)

    return read_sql(
        conn,
        f"""
        SELECT
            concepts.*,
            CASE
                WHEN concepts.review_status = 'pending_review'
                 AND lower(concepts.is_public) = 'true'
                 AND concepts.label != ''
                 AND concepts.description != ''
                 AND concepts.review_reason != 'likely_technical'
                 AND EXISTS (
                    SELECT 1
                    FROM review_word_senses AS senses
                    WHERE senses.concept_slug = concepts.slug
                      AND lower(trim(senses.word_text)) = {CONCEPT_GROUP_EXPR_WITH_ALIAS}
                 )
                THEN 1
                ELSE 0
            END AS likely_correct
        FROM review_concepts AS concepts
        WHERE {where}
        ORDER BY
            likely_correct DESC,
            concepts.priority DESC,
            concepts.slug
        LIMIT ?
        """,
        tuple(params),
    )


def load_word_senses(
    conn: sqlite3.Connection,
    *,
    status: str,
    limit: int,
    search: str,
    concept_slug: str | None = None,
) -> pd.DataFrame:
    params: list[str | int] = [
        status,
    ]

    where = "review_status = ?"

    if concept_slug:
        where += " AND concept_slug = ?"
        params.append(concept_slug)

    if search:
        where += """
        AND (
            word_text LIKE ?
            OR concept_slug LIKE ?
            OR gloss LIKE ?
            OR source_locator LIKE ?
        )
        """
        like = f"%{search}%"
        params.extend(
            [
                like,
                like,
                like,
                like,
            ]
        )

    params.append(limit)

    return read_sql(
        conn,
        f"""
        SELECT *
        FROM review_word_senses
        WHERE {where}
        ORDER BY priority DESC, concept_slug, word_text
        LIMIT ?
        """,
        tuple(params),
    )


def load_words(
    conn: sqlite3.Connection,
    *,
    status: str,
    limit: int,
    search: str,
) -> pd.DataFrame:
    params: list[str | int] = [
        status,
    ]

    where = "review_status = ?"

    if search:
        where += """
        AND (
            text LIKE ?
            OR external_entry_id LIKE ?
            OR notes LIKE ?
        )
        """
        like = f"%{search}%"
        params.extend(
            [
                like,
                like,
                like,
            ]
        )

    params.append(limit)

    return read_sql(
        conn,
        f"""
        SELECT *
        FROM review_words
        WHERE {where}
        ORDER BY priority DESC, text
        LIMIT ?
        """,
        tuple(params),
    )


def load_relationships(
    conn: sqlite3.Connection,
    *,
    status: str,
    limit: int,
    search: str,
    concept_slug: str | None = None,
) -> pd.DataFrame:
    params: list[str | int] = [
        status,
    ]

    where = "relationships.review_status = ?"

    if concept_slug:
        where += """
        AND (
            relationships.source_concept_slug = ?
            OR relationships.target_concept_slug = ?
        )
        """
        params.extend(
            [
                concept_slug,
                concept_slug,
            ]
        )

    if search:
        where += """
        AND (
            relationships.source_concept_slug LIKE ?
            OR relationships.target_concept_slug LIKE ?
            OR relationships.relationship_type LIKE ?
            OR relationships.source_locator LIKE ?
            OR source_concepts.label LIKE ?
            OR target_concepts.label LIKE ?
            OR source_concepts.description LIKE ?
            OR target_concepts.description LIKE ?
        )
        """
        like = f"%{search}%"
        params.extend(
            [
                like,
                like,
                like,
                like,
                like,
                like,
                like,
                like,
            ]
        )

    params.append(limit)

    return read_sql(
        conn,
        f"""
        SELECT
            relationships.*,
            COALESCE(
                source_concepts.label,
                relationships.source_concept_slug
            ) AS source_label,
            COALESCE(
                target_concepts.label,
                relationships.target_concept_slug
            ) AS target_label,
            COALESCE(
                source_concepts.description,
                ''
            ) AS source_description,
            COALESCE(
                target_concepts.description,
                ''
            ) AS target_description
        FROM review_relationships AS relationships
        LEFT JOIN review_concepts AS source_concepts
          ON relationships.source_concept_slug = source_concepts.slug
        LEFT JOIN review_concepts AS target_concepts
          ON relationships.target_concept_slug = target_concepts.slug
        WHERE {where}
        ORDER BY
            relationships.priority DESC,
            CAST(relationships.weight AS REAL) DESC,
            source_label,
            target_label
        LIMIT ?
        """,
        tuple(params),
    )


def load_relationships_with_unreviewed_concepts(
    conn: sqlite3.Connection,
    *,
    limit: int = 300,
) -> pd.DataFrame:
    return read_sql(
        conn,
        """
        SELECT
            relationships.id,
            relationships.source_concept_slug,
            COALESCE(
                source_concepts.label,
                relationships.source_concept_slug
            ) AS source_label,
            COALESCE(
                source_concepts.review_status,
                'missing'
            ) AS source_concept_status,
            relationships.target_concept_slug,
            COALESCE(
                target_concepts.label,
                relationships.target_concept_slug
            ) AS target_label,
            COALESCE(
                target_concepts.review_status,
                'missing'
            ) AS target_concept_status,
            relationships.relationship_type,
            relationships.weight,
            relationships.confidence,
            relationships.source_locator
        FROM review_relationships AS relationships
        LEFT JOIN review_concepts AS source_concepts
          ON relationships.source_concept_slug = source_concepts.slug
        LEFT JOIN review_concepts AS target_concepts
          ON relationships.target_concept_slug = target_concepts.slug
        WHERE relationships.review_status = 'pending_review'
          AND (
              COALESCE(source_concepts.review_status, 'missing') != 'reviewed'
              OR COALESCE(target_concepts.review_status, 'missing') != 'reviewed'
          )
        ORDER BY
            source_concept_status,
            target_concept_status,
            source_label,
            target_label
        LIMIT ?
        """,
        (
            limit,
        ),
    )


def concept_context(
    conn: sqlite3.Connection,
    concept_slug: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    concept = read_sql(
        conn,
        """
        SELECT *
        FROM review_concepts
        WHERE slug = ?
        """,
        (
            concept_slug,
        ),
    )

    senses = read_sql(
        conn,
        """
        SELECT *
        FROM review_word_senses
        WHERE concept_slug = ?
        ORDER BY review_status, word_text
        """,
        (
            concept_slug,
        ),
    )

    relationships = read_sql(
        conn,
        """
        SELECT
            relationships.*,
            COALESCE(
                source_concepts.label,
                relationships.source_concept_slug
            ) AS source_label,
            COALESCE(
                target_concepts.label,
                relationships.target_concept_slug
            ) AS target_label
        FROM review_relationships AS relationships
        LEFT JOIN review_concepts AS source_concepts
        ON relationships.source_concept_slug = source_concepts.slug
        LEFT JOIN review_concepts AS target_concepts
        ON relationships.target_concept_slug = target_concepts.slug
        WHERE relationships.source_concept_slug = ?
        OR relationships.target_concept_slug = ?
        ORDER BY
            relationships.review_status,
            CAST(relationships.weight AS REAL) DESC
        """,
        (
            concept_slug,
            concept_slug,
        ),
    )

    return concept, senses, relationships


def load_status_drilldown(
    conn: sqlite3.Connection,
    *,
    table_label: str,
    status: str,
    search: str = "",
) -> pd.DataFrame:
    config = STATUS_DRILLDOWN_TABLES[table_label]
    table = config["table"]
    columns = config["columns"]
    order_by = config["order_by"]

    column_sql = ", ".join(columns)

    params: list[str] = [status]

    where = "review_status = ?"

    if search:
        searchable_columns = [
            column
            for column in columns
            if column not in {"id", "priority"}
        ]

        search_sql = " OR ".join(
            f"{column} LIKE ?"
            for column in searchable_columns
        )

        where += f" AND ({search_sql})"

        like = f"%{search}%"
        params.extend(
            [
                like
                for _ in searchable_columns
            ]
        )

    return read_sql(
        conn,
        f"""
        SELECT {column_sql}
        FROM {table}
        WHERE {where}
        ORDER BY {order_by}
        """,
        tuple(params),
    )


def render_status_buttons(
    conn: sqlite3.Connection,
    *,
    table: str,
    row_id: int,
    key_prefix: str,
) -> None:
    columns = st.columns(
        [
            1,
            1,
            1,
            1,
            1,
        ]
    )

    actions = [
        ("Accept", "reviewed"),
        ("Reject", "rejected"),
        ("Defer", "deferred"),
        ("Needs edit", "needs_edit"),
        ("Duplicate", "duplicate"),
    ]

    for column, (
        label,
        status,
    ) in zip(columns, actions):
        with column:
            if st.button(
                label,
                key=f"{key_prefix}-{status}-{row_id}",
            ):
                update_status(
                    conn,
                    table,
                    row_id,
                    status,
                )
                st.rerun()


def keyboard_action_box(
    conn: sqlite3.Connection,
    *,
    table: str,
    row_id: int,
    key_prefix: str,
) -> None:
    with st.form(
        key=f"{key_prefix}-keyboard-{row_id}",
        clear_on_submit=True,
    ):
        action = st.text_input(
            "Keyboard-speed action: a=accept, r=reject, d=defer, e=needs edit, x=duplicate",
            value="",
        ).strip().casefold()

        submitted = st.form_submit_button(
            "Apply action"
        )

        if not submitted:
            return

        mapping = {
            "a": "reviewed",
            "r": "rejected",
            "d": "deferred",
            "e": "needs_edit",
            "x": "duplicate",
        }

        status = mapping.get(action)

        if status is None:
            st.error("Unknown action.")
            return

        update_status(
            conn,
            table,
            row_id,
            status,
        )
        st.rerun()


def concept_review_page(
    conn: sqlite3.Connection,
) -> None:
    st.header("Concept review")
    render_review_guide("Concepts")

    unresolved_count = unresolved_concept_group_count(conn)

    metric_col1, metric_col2 = st.columns(2)

    with metric_col1:
        st.metric(
            "Unique concept groups without an accepted concept",
            unresolved_count,
        )

    with metric_col2:
        pending_concepts = read_sql(
            conn,
            """
            SELECT COUNT(*) AS count
            FROM review_concepts
            WHERE review_status = 'pending_review'
            """
        )
        st.metric(
            "Pending concept rows",
            int(pending_concepts.iloc[0]["count"]),
        )

    with st.expander("Unresolved unique concept groups", expanded=False):
        unresolved = unresolved_concept_groups(conn)

        if unresolved.empty:
            st.success(
                "Every pending concept group has at least one reviewed concept."
            )
        else:
            st.dataframe(
                unresolved[
                    [
                        "concept_group",
                        "pending_count",
                        "reviewed_count",
                        "rejected_count",
                        "deferred_count",
                        "candidate_slugs",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

    with st.expander("Danger zone: reject remaining pending concepts"):
        st.warning(
            "This marks every concept row with review_status = pending_review "
            "as rejected. It does not affect word senses, words, or relationships."
        )

        confirm_reject_all = st.checkbox(
            "I understand this will reject all remaining pending concept rows.",
            key="confirm_reject_all_pending_concepts",
        )

        if st.button(
            "Mark all remaining pending concepts as rejected",
            disabled=not confirm_reject_all,
        ):
            changed_count = reject_all_pending_concepts(conn)
            st.success(
                f"Rejected {changed_count} pending concept rows."
            )
            st.rerun()

    status, limit, search = status_filter_sidebar()

    rows = load_concepts(
        conn,
        status=status,
        limit=limit,
        search=search,
    )

    if rows.empty:
        st.success("No concepts match this filter.")
        return

    for _, row in rows.iterrows():
        row_id = int(row["id"])

        with st.container(border=True):
            st.subheader(
                f"{row['label']}  ·  `{row['slug']}`"
            )
            st.write(row["description"])
            
            likely_correct = int(row.get("likely_correct", 0)) == 1

            st.caption(
                f"Domain: {row['domain']} · "
                f"Type: {row['concept_type']} · "
                f"Public: {row['is_public']} · "
                f"Reason: {row['review_reason']} · "
                f"Priority: {row['priority']} · "
                f"Likely correct: {'yes' if likely_correct else 'no'}"
            )

            with st.expander("Edit concept"):
                new_label = st.text_input(
                    "Label",
                    value=row["label"],
                    key=f"concept-label-{row_id}",
                )
                new_domain = st.text_input(
                    "Domain",
                    value=row["domain"],
                    key=f"concept-domain-{row_id}",
                )
                new_notes = st.text_area(
                    "Notes",
                    value=row["notes"],
                    key=f"concept-notes-{row_id}",
                )

                if st.button(
                    "Save concept edits",
                    key=f"save-concept-{row_id}",
                ):
                    update_field(
                        conn,
                        "review_concepts",
                        row_id,
                        "label",
                        new_label,
                    )
                    update_field(
                        conn,
                        "review_concepts",
                        row_id,
                        "domain",
                        new_domain,
                    )
                    update_field(
                        conn,
                        "review_concepts",
                        row_id,
                        "notes",
                        new_notes,
                    )
                    st.rerun()

            concept, senses, relationships = concept_context(
                conn,
                row["slug"],
            )

            st.markdown("**Attached word senses**")
            st.dataframe(
                senses[
                    [
                        "word_text",
                        "part_of_speech",
                        "gloss",
                        "review_status",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

            st.markdown("**Relationships**")
            st.dataframe(
                relationships[
                    [
                        "source_label",
                        "target_label",
                        "relationship_type",
                        "weight",
                        "review_status",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

            render_status_buttons(
                conn,
                table="review_concepts",
                row_id=row_id,
                key_prefix="concept",
            )
            keyboard_action_box(
                conn,
                table="review_concepts",
                row_id=row_id,
                key_prefix="concept",
            )


def word_sense_review_page(
    conn: sqlite3.Connection,
) -> None:
    st.header("Word sense review")
    render_review_guide("Word senses")

    pending_word_senses = read_sql(
        conn,
        """
        SELECT COUNT(*) AS count
        FROM review_word_senses
        WHERE review_status = 'pending_review'
        """
    )

    st.metric(
        "Pending word sense rows",
        int(pending_word_senses.iloc[0]["count"]),
    )

    with st.expander("Danger zone: reject remaining pending word senses"):
        st.warning(
            "This marks every word sense row with review_status = pending_review "
            "as rejected. It does not affect concepts, words, or relationships."
        )

        confirm_reject_all = st.checkbox(
            "I understand this will reject all remaining pending word sense rows.",
            key="confirm_reject_all_pending_word_senses",
        )

        if st.button(
            "Mark all remaining pending word senses as rejected",
            disabled=not confirm_reject_all,
        ):
            changed_count = reject_all_pending_word_senses(conn)
            st.success(
                f"Rejected {changed_count} pending word sense rows."
            )
            st.rerun()

    status, limit, search = status_filter_sidebar()

    concept_filter = st.sidebar.text_input(
        "Concept slug filter",
        value="",
    ).strip()

    rows = load_word_senses(
        conn,
        status=status,
        limit=limit,
        search=search,
        concept_slug=concept_filter or None,
    )

    if rows.empty:
        st.success("No word senses match this filter.")
        return

    for _, row in rows.iterrows():
        row_id = int(row["id"])

        with st.container(border=True):
            st.subheader(
                f"{row['word_text']} → `{row['concept_slug']}`"
            )
            st.write(row["gloss"])
            st.caption(
                f"POS: {row['part_of_speech']} · "
                f"Equivalence: {row['equivalence_type']} · "
                f"Rank: {row['sense_rank']} · "
                f"Confidence: {row['confidence']} · "
                f"Reason: {row['review_reason']} · "
                f"Priority: {row['priority']}"
            )
            st.caption(row["source_locator"])

            with st.expander("Concept context"):
                _, senses, relationships = concept_context(
                    conn,
                    row["concept_slug"],
                )
                st.dataframe(
                    senses[
                        [
                            "word_text",
                            "part_of_speech",
                            "review_status",
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
                st.dataframe(
                    relationships[
                        [
                            "source_label",
                            "target_label",
                            "relationship_type",
                            "weight",
                            "review_status",
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

            with st.expander("Edit word sense"):
                new_concept = st.text_input(
                    "Concept slug",
                    value=row["concept_slug"],
                    key=f"sense-concept-{row_id}",
                )
                new_equivalence = st.selectbox(
                    "Equivalence type",
                    [
                        "canonical",
                        "direct_equivalent",
                        "near_equivalent",
                        "related",
                        "symbolic",
                        "technical",
                        "archaic",
                        "poetic",
                    ],
                    index=[
                        "canonical",
                        "direct_equivalent",
                        "near_equivalent",
                        "related",
                        "symbolic",
                        "technical",
                        "archaic",
                        "poetic",
                    ].index(row["equivalence_type"])
                    if row["equivalence_type"]
                    in {
                        "canonical",
                        "direct_equivalent",
                        "near_equivalent",
                        "related",
                        "symbolic",
                        "technical",
                        "archaic",
                        "poetic",
                    }
                    else 0,
                    key=f"sense-equivalence-{row_id}",
                )
                new_rank = st.text_input(
                    "Sense rank",
                    value=str(row["sense_rank"]),
                    key=f"sense-rank-{row_id}",
                )
                new_notes = st.text_area(
                    "Notes",
                    value=row["notes"],
                    key=f"sense-notes-{row_id}",
                )

                if st.button(
                    "Save word sense edits",
                    key=f"save-sense-{row_id}",
                ):
                    update_field(
                        conn,
                        "review_word_senses",
                        row_id,
                        "concept_slug",
                        new_concept,
                    )
                    update_field(
                        conn,
                        "review_word_senses",
                        row_id,
                        "equivalence_type",
                        new_equivalence,
                    )
                    update_field(
                        conn,
                        "review_word_senses",
                        row_id,
                        "sense_rank",
                        new_rank,
                    )
                    update_field(
                        conn,
                        "review_word_senses",
                        row_id,
                        "notes",
                        new_notes,
                    )
                    st.rerun()

            render_status_buttons(
                conn,
                table="review_word_senses",
                row_id=row_id,
                key_prefix="sense",
            )
            keyboard_action_box(
                conn,
                table="review_word_senses",
                row_id=row_id,
                key_prefix="sense",
            )


def words_review_page(
    conn: sqlite3.Connection,
) -> None:
    st.header("Word form review")
    render_review_guide("Words")

    status, limit, search = status_filter_sidebar()

    rows = load_words(
        conn,
        status=status,
        limit=limit,
        search=search,
    )

    if rows.empty:
        st.success("No words match this filter.")
        return

    st.info(
        "Words are usually exported automatically if a reviewed word sense uses them."
    )

    for _, row in rows.iterrows():
        row_id = int(row["id"])

        with st.container(border=True):
            st.subheader(
                f"{row['text']} · {row['part_of_speech']}"
            )
            st.caption(
                f"Language: {row['language_code']} · "
                f"Source: {row['source_slug']} · "
                f"Reason: {row['review_reason']}"
            )
            st.write(row["notes"])

            render_status_buttons(
                conn,
                table="review_words",
                row_id=row_id,
                key_prefix="word",
            )
            keyboard_action_box(
                conn,
                table="review_words",
                row_id=row_id,
                key_prefix="word",
            )


def relationship_review_page(
    conn: sqlite3.Connection,
) -> None:
    st.header("Relationship review")
    render_review_guide("Relationships")

    pending_concepts = pending_concept_count(conn)

    cleanup_preview = load_relationships_with_unreviewed_concepts(
        conn,
        limit=300,
    )

    metric_col1, metric_col2 = st.columns(2)

    with metric_col1:
        st.metric(
            "Pending concept rows",
            pending_concepts,
        )

    with metric_col2:
        st.metric(
            "Pending relationships with non-reviewed concepts",
            len(cleanup_preview),
        )

    with st.expander(
        "Cleanup: reject relationships involving non-reviewed concepts",
        expanded=False,
    ):
        st.write(
            "Use this after concept review is finished. It rejects pending "
            "relationships where either the source concept or target concept "
            "is not `reviewed`."
        )

        if pending_concepts > 0:
            st.warning(
                "Concept review is not finished yet. Finish accepting/rejecting "
                "concepts before using this cleanup."
            )

        if cleanup_preview.empty:
            st.success(
                "No pending relationships currently involve non-reviewed concepts."
            )
        else:
            st.dataframe(
                cleanup_preview,
                use_container_width=True,
                hide_index=True,
            )

        confirm_cleanup = st.checkbox(
            "I reviewed this preview and want to reject these relationships.",
            key="confirm_reject_relationships_with_unreviewed_concepts",
        )

        if st.button(
            "Reject pending relationships with non-reviewed concepts",
            disabled=(
                pending_concepts > 0
                or cleanup_preview.empty
                or not confirm_cleanup
            ),
        ):
            changed_count = reject_relationships_with_unreviewed_concepts(conn)
            st.success(
                f"Rejected {changed_count} pending relationship rows."
            )
            st.rerun()

    status, limit, search = status_filter_sidebar()

    concept_filter = st.sidebar.text_input(
        "Concept slug filter",
        value="",
    ).strip()

    rows = load_relationships(
        conn,
        status=status,
        limit=limit,
        search=search,
        concept_slug=concept_filter or None,
    )

    if rows.empty:
        st.success("No relationships match this filter.")
        return

    for _, row in rows.iterrows():
        row_id = int(row["id"])

        with st.container(border=True):
            st.subheader(
                f"{row['source_label']} → {row['target_label']}"
            )
            st.caption(
                f"`{row['source_concept_slug']}` → `{row['target_concept_slug']}`"
            )
            st.caption(
                f"Type: {row['relationship_type']} · "
                f"Weight: {row['weight']} · "
                f"Confidence: {row['confidence']} · "
                f"Reason: {row['review_reason']} · "
                f"Priority: {row['priority']}"
            )
            st.caption(row["source_locator"])

            if row["source_description"]:
                st.markdown(
                    f"**Source meaning:** {row['source_description']}"
                )

            if row["target_description"]:
                st.markdown(
                    f"**Target meaning:** {row['target_description']}"
                )

            with st.expander("Edit relationship"):
                new_type = st.selectbox(
                    "Relationship type",
                    [
                        "synonym",
                        "near_synonym",
                        "symbolic",
                        "associated",
                        "broader",
                        "narrower",
                        "contrast",
                    ],
                    index=[
                        "synonym",
                        "near_synonym",
                        "symbolic",
                        "associated",
                        "broader",
                        "narrower",
                        "contrast",
                    ].index(row["relationship_type"])
                    if row["relationship_type"]
                    in {
                        "synonym",
                        "near_synonym",
                        "symbolic",
                        "associated",
                        "broader",
                        "narrower",
                        "contrast",
                    }
                    else 3,
                    key=f"rel-type-{row_id}",
                )
                new_weight = st.text_input(
                    "Weight",
                    value=str(row["weight"]),
                    key=f"rel-weight-{row_id}",
                )
                new_notes = st.text_area(
                    "Notes",
                    value=row["notes"],
                    key=f"rel-notes-{row_id}",
                )

                if st.button(
                    "Save relationship edits",
                    key=f"save-rel-{row_id}",
                ):
                    update_field(
                        conn,
                        "review_relationships",
                        row_id,
                        "relationship_type",
                        new_type,
                    )
                    update_field(
                        conn,
                        "review_relationships",
                        row_id,
                        "weight",
                        new_weight,
                    )
                    update_field(
                        conn,
                        "review_relationships",
                        row_id,
                        "notes",
                        new_notes,
                    )
                    st.rerun()

            col1, col2 = st.columns(2)

            with col1:
                render_status_buttons(
                    conn,
                    table="review_relationships",
                    row_id=row_id,
                    key_prefix="relationship",
                )

            with col2:
                if st.button(
                    "Accept + create reverse relationship",
                    key=f"reverse-{row_id}",
                ):
                    execute(
                        conn,
                        """
                        INSERT INTO review_relationships (
                            source_concept_slug,
                            target_concept_slug,
                            relationship_type,
                            weight,
                            source_slug,
                            source_locator,
                            confidence,
                            review_status,
                            notes,
                            priority,
                            review_reason
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'reviewed', ?, ?, ?)
                        ON CONFLICT(source_concept_slug, target_concept_slug, relationship_type)
                        DO UPDATE SET
                            review_status = 'reviewed',
                            weight = excluded.weight,
                            confidence = excluded.confidence
                        """,
                        (
                            row["target_concept_slug"],
                            row["source_concept_slug"],
                            row["relationship_type"],
                            row["weight"],
                            row["source_slug"],
                            f"reverse:{row['source_locator']}",
                            row["confidence"],
                            "Created from reverse-review button.",
                            row["priority"],
                            "reverse_relationship",
                        ),
                    )
                    update_status(
                        conn,
                        "review_relationships",
                        row_id,
                        "reviewed",
                    )
                    st.rerun()

            keyboard_action_box(
                conn,
                table="review_relationships",
                row_id=row_id,
                key_prefix="relationship",
            )


def batch_review_page(
    conn: sqlite3.Connection,
) -> None:
    st.header("Safe batch review")
    render_review_guide("Batch review")

    st.warning(
        "Batch actions are intentionally conservative. Preview rows before applying."
    )

    action = st.selectbox(
        "Batch action",
        [
            "Preview word senses for reviewed concepts",
            "Preview likely technical concepts",
            "Preview high-priority exact word senses",
            "Preview weak relationships",
        ],
    )

    if action == "Preview word senses for reviewed concepts":
        rows = read_sql(
            conn,
            """
            SELECT
                review_word_senses.id,
                review_word_senses.word_text,
                review_word_senses.part_of_speech,
                review_word_senses.concept_slug,
                review_word_senses.gloss,
                review_word_senses.equivalence_type,
                review_word_senses.sense_rank,
                review_word_senses.confidence,
                review_concepts.label AS concept_label,
                review_concepts.description AS concept_description
            FROM review_word_senses
            JOIN review_concepts
            ON review_word_senses.concept_slug = review_concepts.slug
            WHERE review_word_senses.review_status = 'pending_review'
            AND review_concepts.review_status = 'reviewed'
            AND review_word_senses.word_text != ''
            AND review_word_senses.concept_slug != ''
            AND review_word_senses.gloss != ''
            AND review_word_senses.source_locator != ''
            ORDER BY
                review_word_senses.priority DESC,
                review_word_senses.word_text
            LIMIT 200
            """,
        )
        table = "review_word_senses"
        suggested_status = "reviewed"

    elif action == "Preview likely technical concepts":
        rows = read_sql(
            conn,
            """
            SELECT id, slug, label, description, review_reason
            FROM review_concepts
            WHERE review_status = 'pending_review'
              AND review_reason = 'likely_technical'
            ORDER BY slug
            LIMIT 200
            """,
        )
        table = "review_concepts"
        suggested_status = "deferred"

    elif action == "Preview high-priority exact word senses":
        rows = read_sql(
            conn,
            """
            SELECT id, word_text, concept_slug, gloss, review_reason
            FROM review_word_senses
            WHERE review_status = 'pending_review'
              AND priority >= 85
            ORDER BY priority DESC, word_text
            LIMIT 200
            """,
        )
        table = "review_word_senses"
        suggested_status = "reviewed"

    else:
        rows = read_sql(
            conn,
            """
            SELECT id, source_concept_slug, target_concept_slug, relationship_type, weight
            FROM review_relationships
            WHERE review_status = 'pending_review'
              AND review_reason = 'weak_relationship'
            ORDER BY CAST(weight AS REAL)
            LIMIT 200
            """,
        )
        table = "review_relationships"
        suggested_status = "deferred"

    if action == "Preview word senses for reviewed concepts":
        st.info(
            "This batch accepts pending word senses whose concept has already "
            "been reviewed. Still scan the preview for ambiguous words like "
            "`fire`, `light`, or other words with multiple meanings."
        )

    if rows.empty:
        st.success("No rows match this batch rule.")
        return

    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
    )

    st.write(f"Suggested status: `{suggested_status}`")

    confirm = st.checkbox(
        "I reviewed this preview and want to apply the batch action."
    )

    if st.button("Apply batch action") and confirm:
        ids = [
            int(value)
            for value in rows["id"].tolist()
        ]
        batch_update_status(
            conn,
            table,
            ids,
            suggested_status,
        )
        st.success(
            f"Updated {len(ids)} rows in {table} to {suggested_status}."
        )
        st.rerun()


def export_preview_page(
    conn: sqlite3.Connection,
) -> None:
    st.header("Export preview")
    render_review_guide("Export preview")

    counts = all_progress_counts(conn)

    if counts.empty:
        st.warning("No review tables found.")
        return

    st.dataframe(
        counts,
        use_container_width=True,
        hide_index=True,
    )

    reviewed_counts = read_sql(
        conn,
        """
        SELECT 'concepts' AS output, COUNT(*) AS count
        FROM review_concepts
        WHERE review_status = 'reviewed'
        UNION ALL
        SELECT 'words', COUNT(*)
        FROM review_words
        WHERE review_status = 'reviewed'
        UNION ALL
        SELECT 'word_senses', COUNT(*)
        FROM review_word_senses
        WHERE review_status = 'reviewed'
        UNION ALL
        SELECT 'relationships', COUNT(*)
        FROM review_relationships
        WHERE review_status = 'reviewed'
        UNION ALL
        SELECT 'mappings', COUNT(*)
        FROM review_mappings
        WHERE review_status = 'reviewed'
        """
    )

    st.subheader("Rows that will export")
    st.dataframe(
        reviewed_counts,
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Export reviewed rows")

    base_path_text = st.text_input(
        "Base curated folder",
        value="data/curated/v4",
    )

    output_path_text = st.text_input(
        "New curated output folder",
        value="data/curated/v5",
    )

    candidate_out_text = st.text_input(
        "Temporary reviewed candidate export folder",
        value="data/review/exported-candidates/oewn-2025",
    )

    replace = st.checkbox(
        "Replace output folders if they already exist",
        value=False,
    )

    st.caption(
        "This exports reviewed rows from SQLite into temporary candidate CSVs, "
        "then merges those reviewed rows into a new curated dataset folder."
    )

    if st.button("Export reviewed rows to curated CSVs"):
        try:
            candidate_counts = export_review_db_to_candidate_csvs(
                db_path=DB_PATH,
                candidates_out=Path(candidate_out_text),
                replace=replace,
            )

            added_counts = export_reviewed_oewn_yellow(
                base_path=Path(base_path_text),
                candidates_path=Path(candidate_out_text),
                output_path=Path(output_path_text),
                replace=replace,
            )

            st.success(
                f"Export complete. Created {output_path_text}."
            )

            st.subheader("Temporary candidate CSV export")
            st.json(candidate_counts)

            st.subheader("Rows added to curated dataset")
            st.json(added_counts)

            st.code(
                f"""
python -m app.importers.curated_catalog \\
  --path {output_path_text} \\
  --dry-run

python -m pytest -q
                """.strip(),
                language="bash",
            )

        except Exception as exc:
            st.error("Export failed.")
            st.exception(exc)

    st.subheader("Equivalent terminal command")

    st.code(
        f"""
python -m app.review.export_reviewed \\
  --db {DB_PATH} \\
  --base {base_path_text} \\
  --out {output_path_text} \\
  --candidate-out {candidate_out_text} \\
  {"--replace" if replace else ""}
        """.strip(),
        language="bash",
    )


def main() -> None:
    st.set_page_config(
        page_title="Yellow Card Review",
        layout="wide",
    )

    st.title("Yellow Card Review Workspace")

    if not DB_PATH.exists():
        st.error(
            f"Review database not found: {DB_PATH}. "
            "Run app.review.load_candidates first."
        )
        return

    conn = connect()

    page = st.sidebar.radio(
        "Page",
        [
            "Progress",
            "Concepts",
            "Word senses",
            "Words",
            "Relationships",
            "Batch review",
            "Export preview",
        ],
    )

    if page == "Progress":
        st.header("Review progress")
        render_review_guide("Progress")

        counts = all_progress_counts(conn)

        if counts.empty:
            st.warning("No review data found.")
            return

        st.markdown("### Status counts")

        for table_label in TABLES:
            table_counts = counts[
                counts["table_name"] == table_label
            ]

            if table_counts.empty:
                continue

            with st.container(border=True):
                st.markdown(f"#### {table_label}")

                for _, row in table_counts.iterrows():
                    status = str(row["review_status"])
                    count = int(row["count"])

                    col1, col2, col3 = st.columns(
                        [
                            2,
                            1,
                            1,
                        ]
                    )

                    with col1:
                        st.write(status)

                    with col2:
                        st.write(count)

                    with col3:
                        if st.button(
                            "View",
                            key=f"view-{table_label}-{status}",
                        ):
                            st.session_state["progress_drilldown"] = {
                                "table_label": table_label,
                                "status": status,
                            }
                            st.session_state["progress_drilldown_search"] = ""
                            st.rerun()

        render_status_drilldown(conn)

    elif page == "Concepts":
        concept_review_page(conn)

    elif page == "Word senses":
        word_sense_review_page(conn)

    elif page == "Words":
        words_review_page(conn)

    elif page == "Relationships":
        relationship_review_page(conn)

    elif page == "Batch review":
        batch_review_page(conn)

    elif page == "Export preview":
        export_preview_page(conn)


if __name__ == "__main__":
    main()