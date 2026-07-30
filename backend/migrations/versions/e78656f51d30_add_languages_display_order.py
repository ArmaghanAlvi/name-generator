"""add languages display_order

Revision ID: e78656f51d30
Revises: a8785dcb5b20
Create Date: 2026-07-30 12:45:15.084663

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e78656f51d30'
down_revision: Union[str, Sequence[str], None] = 'a8785dcb5b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Display/interleave ordering, decoupled from id (Stage 8 pre-flight,
    # Breakdown 5 Step 2). NULL = fall back to id (import order), so the
    # column is byte-identical to the old behavior until values are set.
    op.add_column(
        "languages",
        sa.Column("display_order", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("languages", "display_order")
