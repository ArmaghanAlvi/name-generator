from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal

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

VALID_STATUSES = [
    "pending_review",
    "reviewed",
    "rejected",
    "deferred",
    "needs_edit",
    "duplicate",
]

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

    where = "review_status = ?"

    if search:
        where += """
        AND (
            slug LIKE ?
            OR label LIKE ?
            OR description LIKE ?
            OR notes LIKE ?
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
        FROM review_concepts
        WHERE {where}
        ORDER BY priority DESC, slug
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

    where = "review_status = ?"

    if concept_slug:
        where += """
        AND (
            source_concept_slug = ?
            OR target_concept_slug = ?
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
            source_concept_slug LIKE ?
            OR target_concept_slug LIKE ?
            OR relationship_type LIKE ?
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
        FROM review_relationships
        WHERE {where}
        ORDER BY priority DESC, CAST(weight AS REAL) DESC
        LIMIT ?
        """,
        tuple(params),
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
        SELECT *
        FROM review_relationships
        WHERE source_concept_slug = ?
           OR target_concept_slug = ?
        ORDER BY review_status, CAST(weight AS REAL) DESC
        """,
        (
            concept_slug,
            concept_slug,
        ),
    )

    return concept, senses, relationships


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
            st.caption(
                f"Domain: {row['domain']} · "
                f"Type: {row['concept_type']} · "
                f"Public: {row['is_public']} · "
                f"Reason: {row['review_reason']} · "
                f"Priority: {row['priority']}"
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
                        "source_concept_slug",
                        "target_concept_slug",
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
                            "source_concept_slug",
                            "target_concept_slug",
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
                f"{row['source_concept_slug']} → {row['target_concept_slug']}"
            )
            st.caption(
                f"Type: {row['relationship_type']} · "
                f"Weight: {row['weight']} · "
                f"Confidence: {row['confidence']} · "
                f"Reason: {row['review_reason']} · "
                f"Priority: {row['priority']}"
            )
            st.caption(row["source_locator"])

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
            "Preview likely technical concepts",
            "Preview high-priority exact word senses",
            "Preview weak relationships",
        ],
    )

    if action == "Preview likely technical concepts":
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

    st.code(
        """
python -m app.review.export_reviewed \\
  --db data/review/oewn-2025.sqlite \\
  --base data/curated/v4 \\
  --out data/curated/v5 \\
  --replace

python -m app.importers.curated_catalog \\
  --path data/curated/v5 \\
  --dry-run

python -m pytest -q
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
        st.dataframe(
            counts,
            use_container_width=True,
            hide_index=True,
        )

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