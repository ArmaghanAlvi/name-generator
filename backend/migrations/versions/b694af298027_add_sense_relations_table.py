"""add sense_relations table

Revision ID: b694af298027
Revises: d67fd4144c34
Create Date: 2026-06-23 21:49:32.159524

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b694af298027'
down_revision: Union[str, Sequence[str], None] = 'd67fd4144c34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sense_relations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("from_sense_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=40), nullable=False),
        sa.Column("provenance", sa.String(length=20), nullable=False),
        sa.Column("target_text", sa.String(length=300), nullable=False),
        sa.Column("target_normalized", sa.String(length=300), nullable=False),
        sa.Column("target_sense_hint", sa.Text(), nullable=True),
        sa.Column("target_lexeme_id", sa.Integer(), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["from_sense_id"], ["senses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_lexeme_id"], ["lexemes.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "from_sense_id",
            "relation_type",
            "provenance",
            "target_normalized",
            name="uq_sense_relations_edge",
        ),
        sa.CheckConstraint(
            "relation_type IN ('synonym','near_synonym','antonym','hypernym',"
            "'hyponym','derived','related','coordinate')",
            name="ck_sense_relations_type",
        ),
        sa.CheckConstraint(
            "provenance IN ('kaikki','oewn')",
            name="ck_sense_relations_provenance",
        ),
    )
    op.create_index(
        "ix_sense_relations_from_sense", "sense_relations", ["from_sense_id"]
    )
    op.create_index(
        "ix_sense_relations_target_normalized",
        "sense_relations",
        ["target_normalized"],
    )
    op.create_index(
        "ix_sense_relations_type", "sense_relations", ["relation_type"]
    )


def downgrade() -> None:
    op.drop_index("ix_sense_relations_type", table_name="sense_relations")
    op.drop_index(
        "ix_sense_relations_target_normalized", table_name="sense_relations"
    )
    op.drop_index(
        "ix_sense_relations_from_sense", table_name="sense_relations"
    )
    op.drop_table("sense_relations")