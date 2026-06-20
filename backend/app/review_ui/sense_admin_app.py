from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from app.admin.sense_admin_actions import update_sense_admin_override
from app.db.session import SessionLocal
from app.models.generated_name import Language
from app.models.semantic import Lexeme, Sense, SenseEmbedding
from app.services.sense_lookup import lookup_sense_options


st.set_page_config(
    page_title="Sense Admin",
    layout="wide",
)


def load_counts() -> dict[str, int]:
    with SessionLocal() as db:
        lexemes = db.scalar(select(func.count()).select_from(Lexeme)) or 0
        senses = db.scalar(select(func.count()).select_from(Sense)) or 0
        embeddings = (
            db.scalar(select(func.count()).select_from(SenseEmbedding))
            or 0
        )
        hidden = (
            db.scalar(
                select(func.count()).where(
                    Sense.visibility_status == "hidden"
                )
            )
            or 0
        )

    return {
        "lexemes": lexemes,
        "senses": senses,
        "embeddings": embeddings,
        "hidden senses": hidden,
    }


def popular_senses(limit: int = 50) -> pd.DataFrame:
    with SessionLocal() as db:
        rows = db.execute(
            select(
                Lexeme.lemma,
                Language.name,
                Lexeme.part_of_speech,
                Sense.definition,
                Sense.id,
            )
            .join(Sense, Sense.lexeme_id == Lexeme.id)
            .join(Language, Language.id == Lexeme.language_id)
            .order_by(Sense.id)
            .limit(limit)
        ).all()

    return pd.DataFrame(
        rows,
        columns=[
            "word",
            "language",
            "part_of_speech",
            "definition",
            "sense_id",
        ],
    )


def main() -> None:
    st.title("Sense Admin")

    st.markdown(
        """
This is not a prerequisite review queue.

The database already stores imported meanings. This UI is for post-import management:
hide bad senses, pin preferred senses, edit display text, and inspect embedding coverage.
"""
    )

    counts = load_counts()
    st.columns(len(counts))

    st.header("Database summary")
    st.dataframe(
        pd.DataFrame(
            [{"metric": key, "count": value} for key, value in counts.items()]
        ),
        use_container_width=True,
    )

    st.header("Lookup a word")

    col1, col2, col3 = st.columns([3, 1, 1])

    with col1:
        query = st.text_input("Word", value="light")

    with col2:
        language_code = st.text_input("Language code", value="en")

    with col3:
        include_hidden = st.checkbox("Include hidden", value=True)

    if query:
        with SessionLocal() as db:
            options = lookup_sense_options(
                db,
                query=query,
                language_code=language_code or None,
                include_hidden=include_hidden,
                limit=100,
            )

        st.caption(f"Found {len(options)} meanings.")

        for option in options:
            with st.container(border=True):
                st.subheader(
                    f"{option.word} · {option.partOfSpeech} · sense {option.senseId}"
                )
                st.write(option.definition)
                st.caption(
                    f"selected {option.selectionCount} times · "
                    f"pinned rank {option.pinnedRank} · "
                    f"hidden {option.isHidden}"
                )

                with st.expander("Raw metadata"):
                    st.write(
                        {
                            "tags": option.tags,
                            "categories": option.categories,
                            "rawGlosses": option.rawGlosses,
                            "sourceLocator": option.sourceLocator,
                        }
                    )

                edit_cols = st.columns([1, 1, 2, 3, 3])

                with edit_cols[0]:
                    is_hidden = st.checkbox(
                        "Hide",
                        value=option.isHidden,
                        key=f"hide-{option.senseId}",
                    )

                with edit_cols[1]:
                    pinned_rank = st.number_input(
                        "Pin",
                        min_value=0,
                        max_value=9999,
                        value=option.pinnedRank or 0,
                        key=f"pin-{option.senseId}",
                    )

                with edit_cols[2]:
                    label_override = st.text_input(
                        "Label override",
                        value="",
                        key=f"label-{option.senseId}",
                    )

                with edit_cols[3]:
                    definition_override = st.text_area(
                        "Definition override",
                        value="",
                        key=f"definition-{option.senseId}",
                    )

                with edit_cols[4]:
                    notes = st.text_area(
                        "Notes",
                        value="",
                        key=f"notes-{option.senseId}",
                    )

                if st.button(
                    "Save override",
                    key=f"save-{option.senseId}",
                ):
                    with SessionLocal() as db:
                        update_sense_admin_override(
                            db,
                            sense_id=option.senseId,
                            is_hidden=is_hidden,
                            pinned_rank=(
                                pinned_rank
                                if pinned_rank > 0
                                else None
                            ),
                            label_override=label_override,
                            definition_override=definition_override,
                            notes=notes,
                        )

                    st.success("Saved.")
                    st.rerun()

    st.header("Sample senses")
    st.dataframe(popular_senses(), use_container_width=True)


if __name__ == "__main__":
    main()