"""add hnsw index on sense_embeddings

Revision ID: f4e02f72c706
Revises: b694af298027
Create Date: 2026-06-26 02:36:47.786947

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4e02f72c706'
down_revision: Union[str, Sequence[str], None] = 'b694af298027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
# Disable Alembic's per-migration transaction for this revision.
def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sense_embeddings_hnsw_cos "
            "ON sense_embeddings USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_sense_embeddings_hnsw_cos")