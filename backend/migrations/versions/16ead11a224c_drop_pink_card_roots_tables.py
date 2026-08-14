"""drop pink card roots tables

Revision ID: 16ead11a224c
Revises: 7be3d2344216
Create Date: 2026-08-13 20:16:00.492219

Phase A5. The pink-card Root/RootMeaning skeleton is dead architecture; the
ORM classes were removed in the preceding commit. See PHASE_A_ROOT_BOUNDARY.md
for why this is unrelated to root_selection.py's tree-root acquisition and to
the root_llm_attempts ledger, both of which are load-bearing and untouched.

Original DDL: 847e777b2da9_add_semantic_search_tables.py (lines 78-89, 124-132)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '16ead11a224c'
down_revision: Union[str, Sequence[str], None] = '7be3d2344216'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # root_meanings first: it holds the FK to roots.
    op.drop_table("root_meanings")
    op.drop_table("roots")


def downgrade() -> None:
    op.create_table(
        "roots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("language_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=200), nullable=False),
        sa.Column("transliteration", sa.String(length=200), nullable=True),
        sa.Column("root_type", sa.String(length=50), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["language_id"], ["languages.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "root_meanings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("root_id", sa.Integer(), nullable=False),
        sa.Column("concept_id", sa.Integer(), nullable=False),
        sa.Column("gloss", sa.String(length=300), nullable=False),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["root_id"], ["roots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )