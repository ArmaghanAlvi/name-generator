"""widen sense_relations provenance for 15-language batch

Revision ID: 7be3d2344216
Revises: e78656f51d30
Create Date: 2026-07-30 18:17:39.570198

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7be3d2344216'
down_revision: Union[str, Sequence[str], None] = 'e78656f51d30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_sense_relations_provenance", "sense_relations", type_="check"
    )
    op.create_check_constraint(
        "ck_sense_relations_provenance",
        "sense_relations",
        "provenance IN ("
        "'kaikki','oewn','omw-ja','omw-arb','awn4',"
        "'omw-es','omw-el','omw-pl','omw-he','omw-cmn','odenet','lsg'"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_sense_relations_provenance", "sense_relations", type_="check"
    )
    op.create_check_constraint(
        "ck_sense_relations_provenance",
        "sense_relations",
        "provenance IN ('kaikki','oewn','omw-ja','omw-arb','awn4')",
    )
