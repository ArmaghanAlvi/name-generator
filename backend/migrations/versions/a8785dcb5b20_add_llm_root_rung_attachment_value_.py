"""add llm root rung: attachment value + attempts ledger

Revision ID: a8785dcb5b20
Revises: 0ca5c091ffa7
Create Date: 2026-07-24 16:18:19.183197

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8785dcb5b20'
down_revision: Union[str, Sequence[str], None] = '0ca5c091ffa7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_sense_translations_attachment",
                       "sense_translations", type_="check")
    op.create_check_constraint(
        "ck_sense_translations_attachment", "sense_translations",
        "attachment IN ('sense','dis1','hint','llm')",
    )
    op.create_table(
        "root_llm_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sense_id", sa.Integer(), nullable=False),
        sa.Column("language_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("proposed", sa.JSON(), nullable=False),
        sa.Column("resolved_lexeme_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["sense_id"], ["senses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["language_id"], ["languages.id"]),
        sa.ForeignKeyConstraint(["resolved_lexeme_id"], ["lexemes.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('resolved','unresolved','error')",
                           name="ck_root_llm_attempts_status"),
        sa.UniqueConstraint("sense_id", "language_id",
                            name="uq_root_llm_attempts_pair"),
    )

def downgrade() -> None:
    op.drop_table("root_llm_attempts")
    op.drop_constraint("ck_sense_translations_attachment",
                       "sense_translations", type_="check")
    op.create_check_constraint(
        "ck_sense_translations_attachment", "sense_translations",
        "attachment IN ('sense','dis1','hint')",
    )
