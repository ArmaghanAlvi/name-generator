"""harden semantic ingestion

Revision ID: 7bcecf53a3cc
Revises: 847e777b2da9
Create Date: 2026-06-11 18:04:37.738091

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7bcecf53a3cc'
down_revision: Union[str, Sequence[str], None] = '847e777b2da9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "languages",
        sa.Column("code", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "languages",
        sa.Column("native_name", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "languages",
        sa.Column("script", sa.String(length=100), nullable=True),
    )
    op.create_unique_constraint(
        "uq_languages_code",
        "languages",
        ["code"],
    )

    op.add_column(
        "sources",
        sa.Column("slug", sa.String(length=120), nullable=True),
    )
    op.create_unique_constraint(
        "uq_sources_slug",
        "sources",
        ["slug"],
    )

    op.add_column(
        "concepts",
        sa.Column("domain", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "concepts",
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="active",
        ),
    )
    op.create_check_constraint(
        "ck_concepts_status",
        "concepts",
        "status IN ('active', 'draft', 'retired')",
    )

    op.create_unique_constraint(
        "uq_concept_aliases_concept_normalized_text",
        "concept_aliases",
        ["concept_id", "normalized_text"],
    )
    op.create_index(
        "ix_concept_aliases_normalized_text",
        "concept_aliases",
        ["normalized_text"],
        unique=False,
    )

    op.add_column(
        "concept_relationships",
        sa.Column("source_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "concept_relationships",
        sa.Column("source_locator", sa.Text(), nullable=True),
    )
    op.add_column(
        "concept_relationships",
        sa.Column(
            "confidence",
            sa.String(length=20),
            nullable=False,
            server_default="medium",
        ),
    )
    op.add_column(
        "concept_relationships",
        sa.Column(
            "review_status",
            sa.String(length=20),
            nullable=False,
            server_default="unreviewed",
        ),
    )
    op.create_foreign_key(
        "fk_concept_relationships_source_id_sources",
        "concept_relationships",
        "sources",
        ["source_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_concept_relationships_source_target_type",
        "concept_relationships",
        [
            "source_concept_id",
            "target_concept_id",
            "relationship_type",
        ],
    )
    op.create_check_constraint(
        "ck_concept_relationships_weight_range",
        "concept_relationships",
        "weight >= 0 AND weight <= 1",
    )
    op.create_check_constraint(
        "ck_concept_relationships_confidence",
        "concept_relationships",
        "confidence IN ('high', 'medium', 'low')",
    )
    op.create_check_constraint(
        "ck_concept_relationships_review_status",
        "concept_relationships",
        "review_status IN ('unreviewed', 'reviewed', 'rejected')",
    )
    op.create_index(
        "ix_concept_relationships_source_concept_id",
        "concept_relationships",
        ["source_concept_id"],
        unique=False,
    )
    op.create_index(
        "ix_concept_relationships_target_concept_id",
        "concept_relationships",
        ["target_concept_id"],
        unique=False,
    )

    op.create_unique_constraint(
        "uq_words_language_normalized_text",
        "words",
        ["language_id", "normalized_text"],
    )
    op.create_index(
        "ix_words_language_id",
        "words",
        ["language_id"],
        unique=False,
    )

    op.add_column(
        "word_senses",
        sa.Column("source_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "word_senses",
        sa.Column("source_locator", sa.Text(), nullable=True),
    )
    op.add_column(
        "word_senses",
        sa.Column(
            "confidence",
            sa.String(length=20),
            nullable=False,
            server_default="medium",
        ),
    )
    op.add_column(
        "word_senses",
        sa.Column(
            "review_status",
            sa.String(length=20),
            nullable=False,
            server_default="unreviewed",
        ),
    )
    op.create_foreign_key(
        "fk_word_senses_source_id_sources",
        "word_senses",
        "sources",
        ["source_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_word_senses_word_concept",
        "word_senses",
        ["word_id", "concept_id"],
    )
    op.create_check_constraint(
        "ck_word_senses_confidence",
        "word_senses",
        "confidence IN ('high', 'medium', 'low')",
    )
    op.create_check_constraint(
        "ck_word_senses_review_status",
        "word_senses",
        "review_status IN ('unreviewed', 'reviewed', 'rejected')",
    )
    op.create_index(
        "ix_word_senses_concept_id",
        "word_senses",
        ["concept_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('uq_words_language_normalized_text', 'words', type_='unique')
    op.drop_index('ix_words_language_id', table_name='words')
    op.drop_constraint(None, 'word_senses', type_='foreignkey')
    op.drop_constraint('uq_word_senses_word_concept', 'word_senses', type_='unique')
    op.drop_index('ix_word_senses_concept_id', table_name='word_senses')
    op.drop_column('word_senses', 'review_status')
    op.drop_column('word_senses', 'confidence')
    op.drop_column('word_senses', 'source_locator')
    op.drop_column('word_senses', 'source_id')
    op.drop_constraint('uq_sources_slug', 'sources', type_='unique')
    op.drop_column('sources', 'slug')
    op.drop_column('concepts', 'status')
    op.drop_column('concepts', 'domain')
    op.drop_constraint(None, 'concept_relationships', type_='foreignkey')
    op.drop_constraint('uq_concept_relationships_source_target_type', 'concept_relationships', type_='unique')
    op.drop_index('ix_concept_relationships_target_concept_id', table_name='concept_relationships')
    op.drop_index('ix_concept_relationships_source_concept_id', table_name='concept_relationships')
    op.drop_column('concept_relationships', 'review_status')
    op.drop_column('concept_relationships', 'confidence')
    op.drop_column('concept_relationships', 'source_locator')
    op.drop_column('concept_relationships', 'source_id')
    op.drop_constraint('uq_concept_aliases_concept_normalized_text', 'concept_aliases', type_='unique')
    op.drop_index('ix_concept_aliases_normalized_text', table_name='concept_aliases')
    # ### end Alembic commands ###
