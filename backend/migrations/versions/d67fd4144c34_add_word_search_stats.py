"""add word search stats

Revision ID: d67fd4144c34
Revises: c1f20b8e7a20
Create Date: 2026-06-21 22:37:49.159569

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd67fd4144c34'
down_revision: Union[str, Sequence[str], None] = 'c1f20b8e7a20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "word_search_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("language_id", sa.Integer(), nullable=False),
        sa.Column("normalized_lemma", sa.String(length=300), nullable=False),
        sa.Column(
            "search_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "last_searched_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["language_id"], ["languages.id"]),
        sa.UniqueConstraint(
            "language_id",
            "normalized_lemma",
            name="uq_word_search_stats_language_lemma",
        ),
    )
    op.create_index(
        "ix_word_search_stats_language_lemma",
        "word_search_stats",
        ["language_id", "normalized_lemma"],
    )
    op.create_index(
        "ix_word_search_stats_count",
        "word_search_stats",
        ["search_count"],
    )

    op.create_table(
        "word_search_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("language_id", sa.Integer(), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("normalized_query", sa.String(length=300), nullable=False),
        sa.Column(
            "searched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["language_id"], ["languages.id"]),
    )
    op.create_index(
        "ix_word_search_events_language_query",
        "word_search_events",
        ["language_id", "normalized_query"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_word_search_events_language_query",
        table_name="word_search_events",
    )
    op.drop_table("word_search_events")

    op.drop_index(
        "ix_word_search_stats_count",
        table_name="word_search_stats",
    )
    op.drop_index(
        "ix_word_search_stats_language_lemma",
        table_name="word_search_stats",
    )
    op.drop_table("word_search_stats")