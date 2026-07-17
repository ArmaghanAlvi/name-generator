"""add sense_synsets and widen relation provenance

Revision ID: 7616065f9c69
Revises: f4e02f72c706
Create Date: 2026-07-16 22:17:22.210239

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7616065f9c69'
down_revision: Union[str, Sequence[str], None] = 'f4e02f72c706'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_sense_relations_provenance", "sense_relations", type_="check"
    )
    op.create_check_constraint(
        "ck_sense_relations_provenance",
        "sense_relations",
        "provenance IN ('kaikki','oewn','omw-ja','omw-arb','awn4')",
    )

    op.create_table(
        "sense_synsets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sense_id", sa.Integer(), nullable=False),
        sa.Column("ili", sa.String(length=20), nullable=False),
        sa.Column("source_synset_id", sa.String(length=120), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["sense_id"], ["senses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sense_id", "ili", "source_id", name="uq_sense_synsets_membership"
        ),
    )
    op.create_index("ix_sense_synsets_ili", "sense_synsets", ["ili"])
    op.create_index("ix_sense_synsets_sense", "sense_synsets", ["sense_id"])


def downgrade() -> None:
    op.drop_index("ix_sense_synsets_sense", table_name="sense_synsets")
    op.drop_index("ix_sense_synsets_ili", table_name="sense_synsets")
    op.drop_table("sense_synsets")
    op.drop_constraint(
        "ck_sense_relations_provenance", "sense_relations", type_="check"
    )
    op.create_check_constraint(
        "ck_sense_relations_provenance",
        "sense_relations",
        "provenance IN ('kaikki','oewn')",
    )
