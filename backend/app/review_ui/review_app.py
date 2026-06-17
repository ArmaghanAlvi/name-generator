from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st


DB_PATH = Path("data/review/oewn-2025.sqlite")


def connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def load_pending_word_senses(
    conn: sqlite3.Connection,
    limit: int = 50,
) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT
            id,
            word_text,
            part_of_speech,
            concept_slug,
            gloss,
            equivalence_type,
            sense_rank,
            confidence,
            review_status,
            source_locator
        FROM review_word_senses
        WHERE review_status = 'pending_review'
        ORDER BY confidence DESC, word_text
        LIMIT ?
        """,
        conn,
        params=(limit,),
    )


def update_status(
    conn: sqlite3.Connection,
    table: str,
    row_id: int,
    status: str,
) -> None:
    conn.execute(
        f"""
        UPDATE {table}
        SET review_status = ?
        WHERE id = ?
        """,
        (status, row_id),
    )
    conn.commit()


def main() -> None:
    st.set_page_config(
        page_title="Yellow Card Review",
        layout="wide",
    )

    st.title("Yellow Card Candidate Review")

    conn = connect()

    page = st.sidebar.radio(
        "Review page",
        [
            "Word senses",
            "Concepts",
            "Relationships",
            "Export preview",
        ],
    )

    if page == "Word senses":
        st.header("Pending word senses")

        rows = load_pending_word_senses(conn)

        if rows.empty:
            st.success("No pending word senses.")
            return

        for _, row in rows.iterrows():
            with st.container(border=True):
                st.subheader(
                    f"{row['word_text']} → {row['concept_slug']}"
                )

                st.write(f"Part of speech: `{row['part_of_speech']}`")
                st.write(f"Gloss: {row['gloss']}")
                st.write(f"Equivalence: `{row['equivalence_type']}`")
                st.write(f"Rank: `{row['sense_rank']}`")
                st.write(f"Confidence: `{row['confidence']}`")
                st.caption(row["source_locator"])

                col1, col2, col3 = st.columns(3)

                with col1:
                    if st.button(
                        "Accept",
                        key=f"accept-{row['id']}",
                    ):
                        update_status(
                            conn,
                            "review_word_senses",
                            int(row["id"]),
                            "reviewed",
                        )
                        st.rerun()

                with col2:
                    if st.button(
                        "Reject",
                        key=f"reject-{row['id']}",
                    ):
                        update_status(
                            conn,
                            "review_word_senses",
                            int(row["id"]),
                            "rejected",
                        )
                        st.rerun()

                with col3:
                    if st.button(
                        "Defer",
                        key=f"defer-{row['id']}",
                    ):
                        update_status(
                            conn,
                            "review_word_senses",
                            int(row["id"]),
                            "deferred",
                        )
                        st.rerun()


if __name__ == "__main__":
    main()