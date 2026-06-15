from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import streamlit as st


REVIEW_STATUSES = [
    "pending_review",
    "reviewed",
    "rejected",
    "deferred",
]

def require_row_index(value: int | str | None) -> int:
    if value is None:
        raise ValueError("Expected a selected candidate row, but got None.")

    index = int(value)

    if index < 0:
        raise ValueError(f"Row index cannot be negative: {index}")

    return index

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--path",
        type=Path,
        required=True,
        help="Path to candidate_word_senses.csv",
    )

    args, _unknown = parser.parse_known_args()
    return args


def load_candidates(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Could not find candidate file: {path}"
        )

    df = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
    )

    required_columns = {
        "source_slug",
        "language_code",
        "word_text",
        "part_of_speech",
        "concept_slug",
        "gloss",
        "match_method",
        "match_confidence",
        "source_locator",
        "review_status",
        "notes",
    }

    missing = required_columns - set(df.columns)

    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(
            f"Missing required columns: {missing_list}"
        )

    df = df.reset_index(drop=True)

    # Internal-only row number. This preserves the original CSV order
    # for deterministic navigation. It should not be written back to CSV.
    df["_csv_row_number"] = df.index

    return df


def save_candidates(
    df: pd.DataFrame,
    path: Path,
) -> None:
    output_df = df.drop(
        columns=["_csv_row_number"],
        errors="ignore",
    )

    output_df.to_csv(
        path,
        index=False,
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    path = args.path

    st.set_page_config(
        page_title="Candidate Word Sense Reviewer",
        layout="wide",
    )

    st.title("Candidate Word Sense Reviewer")

    st.markdown(
        """
        <style>
        /* Make disabled input text darker and easier to read */
        input:disabled,
        textarea:disabled {
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
            opacity: 1 !important;
        }

        /* Slightly darken labels too */
        label,
        .stTextInput label,
        .stTextArea label,
        .stSelectbox label {
            color: #1f2937 !important;
        }

        /* Make success/error review messages easier to notice */
        div[data-testid="stAlert"] {
            font-weight: 600;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.caption(
        f"Editing: `{path}`"
    )

    if "df" not in st.session_state:
        st.session_state.df = load_candidates(path)

    df: pd.DataFrame = st.session_state.df

    with st.sidebar:
        st.header("Filters")

        status_filter = st.selectbox(
            "Review status",
            [
                "all",
                *REVIEW_STATUSES,
            ],
            index=1,
        )

        concept_options = [
            "all",
            *sorted(df["concept_slug"].unique()),
        ]

        concept_filter = st.selectbox(
            "Concept",
            concept_options,
        )

        method_options = [
            "all",
            *sorted(df["match_method"].unique()),
        ]

        method_filter = st.selectbox(
            "Match method",
            method_options,
        )

        search_text = st.text_input(
            "Search word/gloss",
            "",
        ).strip().casefold()

    # This broader filtered list is used for:
    # - Prev / Next navigation
    # - the bottom final-review table
    #
    # Important: it does NOT remove reviewed/rejected rows.
    browsable = df.copy()

    if concept_filter != "all":
        browsable = browsable[
            browsable["concept_slug"] == concept_filter
        ]

    if method_filter != "all":
        browsable = browsable[
            browsable["match_method"] == method_filter
        ]

    if search_text:
        browsable = browsable[
            browsable["word_text"]
            .str.casefold()
            .str.contains(search_text, regex=False)
            | browsable["gloss"]
            .str.casefold()
            .str.contains(search_text, regex=False)
        ]

    browsable = browsable.sort_values(
        "_csv_row_number"
    )

    # This narrower list is used only for the dropdown queue.
    # By default, reviewed/rejected rows are removed from the dropdown,
    # but they remain available through Prev / Next and the table.
    filtered = browsable.copy()

    if status_filter != "all":
        filtered = filtered[
            filtered["review_status"] == status_filter
        ]
    else:
        filtered = filtered[
            filtered["review_status"].isin(
                [
                    "pending_review",
                    "deferred",
                ]
            )
        ]

    filtered = filtered.sort_values(
        "_csv_row_number"
    )
    
    st.subheader("Progress")

    counts = (
        df["review_status"]
        .value_counts()
        .reindex(REVIEW_STATUSES, fill_value=0)
    )

    st.write(
        {
            status: int(counts[status])
            for status in REVIEW_STATUSES
        }
    )

    st.subheader("Filtered Candidates")

    st.write(
        f"Dropdown queue: {len(filtered)} rows. "
        f"Browsable/table rows: {len(browsable)} of {len(df)} total."
    )

    if browsable.empty:
        st.info("No rows match the current concept/method/search filters.")
        return

    if filtered.empty:
        st.info(
            "No unreviewed rows remain in the dropdown queue for these filters. "
            "You can still use the table below or change the Review status filter "
            "to view already marked rows."
        )

    total_rows = len(df)

    if total_rows == 0:
        st.info("The candidate file has no rows.")
        return

    # Single source of truth for the main displayed candidate.
    # This is the actual row index in the CSV data:
    # 0 = first data row, which is line 2 of the CSV.
    if "current_row_index" not in st.session_state:
        st.session_state.current_row_index = 0

    current_row_index = require_row_index(
        st.session_state.current_row_index
    )

    if current_row_index >= total_rows:
        current_row_index = total_rows - 1
        st.session_state.current_row_index = current_row_index

    selected_index = current_row_index
    selected_position = selected_index
    row = df.loc[selected_index]

    # This queue is only for the dropdown. It excludes reviewed/rejected
    # rows, but it does NOT control normal Prev/Next navigation.
    queue_indices = list(
        df[
            ~df["review_status"].isin(
                [
                    "reviewed",
                    "rejected",
                ]
            )
        ]
        .sort_values("_csv_row_number")
        .index
    )

    if queue_indices:
        queue_position = (
            queue_indices.index(selected_index)
            if selected_index in queue_indices
            else 0
        )

        queue_choice = st.selectbox(
            "Select candidate row from review queue",
            queue_indices,
            index=queue_position,
            format_func=lambda idx: (
                f"Row {int(idx)}: "
                f"{df.at[idx, 'word_text']} → "
                f"{df.at[idx, 'concept_slug']} "
                f"({df.at[idx, 'match_confidence']}, "
                f"{df.at[idx, 'match_method']})"
            ),
        )

        jump_clicked = st.button(
            "Jump to selected queue row",
            use_container_width=True,
        )

        if jump_clicked:
            st.session_state.current_row_index = require_row_index(
                queue_choice
            )
            st.rerun()
    else:
        st.selectbox(
            "Select candidate row from review queue",
            ["No unreviewed/deferred rows in queue"],
            disabled=True,
        )

    st.caption(
        f"Viewing row {selected_index} of {total_rows - 1} "
        f"(CSV line {selected_index + 2})."
    )
    
    # Reset the editable form widgets whenever the displayed row changes
    # so that notes/status from a previous row don't bleed into the next
    # one via Streamlit's per-position widget state.
    if st.session_state.get("_form_row") != selected_index:
        st.session_state["_form_row"] = selected_index
        st.session_state["_form_status"] = (
            str(row["review_status"])
            if row["review_status"] in REVIEW_STATUSES
            else "pending_review"
        )
        st.session_state["_form_notes"] = str(row["notes"])

    left, right = st.columns([1, 1])

    with left:
        st.markdown("### Candidate")

        st.text_input(
            "Word",
            row["word_text"],
            disabled=True,
        )

        st.text_input(
            "Part of speech",
            row["part_of_speech"],
            disabled=True,
        )

        st.text_input(
            "Proposed concept",
            row["concept_slug"],
            disabled=True,
        )

        st.text_input(
            "Match method",
            row["match_method"],
            disabled=True,
        )

        st.text_input(
            "Match confidence",
            row["match_confidence"],
            disabled=True,
        )

        st.text_input(
            "Source locator",
            row["source_locator"],
            disabled=True,
        )

    with right:
        st.markdown("### Definition / Gloss")

        st.text_area(
            "Gloss",
            row["gloss"],
            height=180,
            disabled=True,
        )

        new_status = st.selectbox(
            "Review status",
            REVIEW_STATUSES,
            key="_form_status",
        )

        new_notes = st.text_area(
            "Reviewer notes",
            key="_form_notes",
            height=120,
        )

    button_cols = st.columns(5)

    with button_cols[0]:
        reviewed_clicked = st.button(
            "Mark reviewed",
            use_container_width=True,
        )

    with button_cols[1]:
        rejected_clicked = st.button(
            "Reject",
            use_container_width=True,
        )

    with button_cols[2]:
        deferred_clicked = st.button(
            "Defer",
            use_container_width=True,
        )

    with button_cols[3]:
        save_clicked = st.button(
            "Save row",
            use_container_width=True,
        )

    with button_cols[4]:
        save_file_clicked = st.button(
            "Save CSV",
            use_container_width=True,
        )

    can_go_prev = selected_index > 0
    can_go_next = selected_index < total_rows - 1

    def go_to_row(index: int) -> None:
        bounded_index = max(
            0,
            min(index, total_rows - 1),
        )

        st.session_state.current_row_index = bounded_index
        st.rerun()

    def auto_go_next() -> None:
        if selected_index < total_rows - 1:
            time.sleep(1)
            st.session_state.current_row_index = selected_index + 1
            st.rerun()


    if reviewed_clicked:
        df.at[selected_index, "review_status"] = "reviewed"
        df.at[selected_index, "notes"] = new_notes
        st.success("Marked as reviewed.")
        auto_go_next()

    if rejected_clicked:
        df.at[selected_index, "review_status"] = "rejected"
        df.at[selected_index, "notes"] = new_notes
        st.error("Marked as rejected.")
        auto_go_next()

    if deferred_clicked:
        df.at[selected_index, "review_status"] = "deferred"
        df.at[selected_index, "notes"] = new_notes
        st.warning("Marked as deferred.")
        auto_go_next()

    if save_clicked:
        df.at[selected_index, "review_status"] = new_status
        df.at[selected_index, "notes"] = new_notes
        st.success("Saved row in memory.")

    if save_file_clicked:
        save_candidates(
            df,
            path,
        )
        st.success(
            f"Saved changes to {path}"
        )

    nav_cols = st.columns(5)

    with nav_cols[0]:
        if can_go_prev:
            if st.button(
                "← Prev",
                use_container_width=True,
            ):
                go_to_row(selected_index - 1)
        else:
            st.empty()

    with nav_cols[1]:
        st.empty()

    with nav_cols[2]:
        st.empty()

    with nav_cols[3]:
        st.empty()

    with nav_cols[4]:
        if can_go_next:
            if st.button(
                "Next →",
                use_container_width=True,
            ):
                go_to_row(selected_index + 1)
        else:
            st.empty()

    st.divider()

    st.subheader("Bulk Table Editor")

    st.caption(
        "This table keeps reviewed/rejected rows visible for final checking. "
        "You can edit review_status and notes directly here. "
        "Click Save CSV afterward to write changes to disk."
    )

    editable_columns = [
        "word_text",
        "concept_slug",
        "gloss",
        "match_method",
        "match_confidence",
        "review_status",
        "notes",
        "source_locator",
    ]

    edited = st.data_editor(
        df[editable_columns],
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "review_status": st.column_config.SelectboxColumn(
                "review_status",
                options=REVIEW_STATUSES,
                required=True,
            )
        },
        disabled=[
            "word_text",
            "concept_slug",
            "gloss",
            "match_method",
            "match_confidence",
            "source_locator",
        ],
    )

    if st.button(
        "Apply visible table edits",
        use_container_width=True,
    ):
        for idx in edited.index:
            df.at[idx, "review_status"] = edited.at[
                idx,
                "review_status",
            ]
            df.at[idx, "notes"] = edited.at[
                idx,
                "notes",
            ]

        st.success("Applied visible table edits in memory.")


if __name__ == "__main__":
    main()