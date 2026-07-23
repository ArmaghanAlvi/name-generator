"""add sense_translations

Revision ID: 0ca5c091ffa7
Revises: 7616065f9c69
Create Date: 2026-07-23 09:46:31.797238

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0ca5c091ffa7'
down_revision: Union[str, Sequence[str], None] = '7616065f9c69'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sense_translations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sense_id", sa.Integer(), nullable=False),
        sa.Column("language_id", sa.Integer(), nullable=False),
        sa.Column("target_text", sa.String(length=300), nullable=False),
        sa.Column("target_normalized", sa.String(length=300), nullable=False),
        sa.Column("target_lexeme_id", sa.Integer(), nullable=True),
        sa.Column("roman", sa.String(length=300), nullable=True),
        sa.Column("attachment", sa.String(length=12), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(["sense_id"], ["senses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["language_id"], ["languages.id"]),
        sa.ForeignKeyConstraint(["target_lexeme_id"], ["lexemes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "attachment IN ('sense','dis1','hint')",
            name="ck_sense_translations_attachment",
        ),
        sa.UniqueConstraint(
            "sense_id", "language_id", "target_normalized",
            name="uq_sense_translations_link",
        ),
    )
    op.create_index("ix_sense_translations_sense", "sense_translations", ["sense_id"])
    op.create_index("ix_sense_translations_lang_norm", "sense_translations",
                    ["language_id", "target_normalized"])
    op.create_index("ix_sense_translations_target_lexeme", "sense_translations",
                    ["target_lexeme_id"])


def downgrade() -> None:
    op.drop_index("ix_sense_translations_target_lexeme", table_name="sense_translations")
    op.drop_index("ix_sense_translations_lang_norm", table_name="sense_translations")
    op.drop_index("ix_sense_translations_sense", table_name="sense_translations")
    op.drop_table("sense_translations")
