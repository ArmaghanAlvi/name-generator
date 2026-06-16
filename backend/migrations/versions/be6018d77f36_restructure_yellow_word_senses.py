"""restructure yellow word senses

Revision ID: be6018d77f36
Revises: 7bcecf53a3cc
Create Date: 2026-06-15 22:28:18.619960

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be6018d77f36'
down_revision: Union[str, Sequence[str], None] = '7bcecf53a3cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # ------------------------------------------------------------
    # concepts: add public/external concept metadata
    # ------------------------------------------------------------

    op.add_column(
        "concepts",
        sa.Column(
            "concept_type",
            sa.String(length=50),
            nullable=False,
            server_default="curated",
        ),
    )

    op.add_column(
        "concepts",
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    op.add_column(
        "concepts",
        sa.Column(
            "external_source_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.add_column(
        "concepts",
        sa.Column(
            "external_concept_id",
            sa.String(length=200),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "fk_concepts_external_source_id_sources",
        "concepts",
        "sources",
        ["external_source_id"],
        ["id"],
    )

    op.create_unique_constraint(
        "uq_concepts_external_source_concept_id",
        "concepts",
        ["external_source_id", "external_concept_id"],
    )

    op.create_check_constraint(
        "ck_concepts_concept_type",
        "concepts",
        (
            "concept_type IN "
            "('curated', 'external_synset', "
            "'imported_candidate', 'merged', 'retired')"
        ),
    )

    op.create_index(
        "ix_concepts_concept_type",
        "concepts",
        ["concept_type"],
        unique=False,
    )

    # ------------------------------------------------------------
    # concept_mappings: map external synset concepts to app concepts
    # ------------------------------------------------------------

    op.create_table(
        "concept_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_concept_id", sa.Integer(), nullable=False),
        sa.Column("target_concept_id", sa.Integer(), nullable=False),
        sa.Column("mapping_type", sa.String(length=50), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("source_locator", sa.Text(), nullable=True),
        sa.Column(
            "confidence",
            sa.String(length=20),
            nullable=False,
            server_default="medium",
        ),
        sa.Column(
            "review_status",
            sa.String(length=20),
            nullable=False,
            server_default="unreviewed",
        ),
        sa.ForeignKeyConstraint(
            ["source_concept_id"],
            ["concepts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_concept_id"],
            ["concepts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_concept_id",
            "target_concept_id",
            "mapping_type",
            name="uq_concept_mappings_source_target_type",
        ),
        sa.CheckConstraint(
            "weight >= 0 AND weight <= 1",
            name="ck_concept_mappings_weight_range",
        ),
        sa.CheckConstraint(
            "mapping_type IN ('exact', 'near', 'broader', 'narrower', 'related')",
            name="ck_concept_mappings_mapping_type",
        ),
        sa.CheckConstraint(
            "confidence IN ('high', 'medium', 'low')",
            name="ck_concept_mappings_confidence",
        ),
        sa.CheckConstraint(
            "review_status IN ('unreviewed', 'reviewed', 'rejected')",
            name="ck_concept_mappings_review_status",
        ),
    )

    op.create_index(
        "ix_concept_mappings_source_concept_id",
        "concept_mappings",
        ["source_concept_id"],
        unique=False,
    )

    op.create_index(
        "ix_concept_mappings_target_concept_id",
        "concept_mappings",
        ["target_concept_id"],
        unique=False,
    )

    # ------------------------------------------------------------
    # words: allow source/external lexical-entry identity
    # ------------------------------------------------------------

    op.add_column(
        "words",
        sa.Column(
            "external_entry_id",
            sa.String(length=200),
            nullable=True,
        ),
    )

    op.drop_constraint(
        op.f("uq_words_language_normalized_text"),
        "words",
        type_="unique",
    )

    op.create_unique_constraint(
        "uq_words_language_normalized_text_pos",
        "words",
        ["language_id", "normalized_text", "part_of_speech"],
    )

    op.create_index(
        "ix_words_external_entry_id",
        "words",
        ["external_entry_id"],
        unique=False,
    )

    # ------------------------------------------------------------
    # word_senses: make senses source-backed and rankable
    # ------------------------------------------------------------

    op.alter_column(
        "word_senses",
        "gloss",
        existing_type=sa.VARCHAR(length=300),
        type_=sa.Text(),
        existing_nullable=False,
    )

    op.add_column(
        "word_senses",
        sa.Column(
            "equivalence_type",
            sa.String(length=50),
            nullable=False,
            server_default="direct_equivalent",
        ),
    )

    op.add_column(
        "word_senses",
        sa.Column(
            "sense_rank",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )

    op.add_column(
        "word_senses",
        sa.Column(
            "external_sense_id",
            sa.String(length=200),
            nullable=True,
        ),
    )

    op.add_column(
        "word_senses",
        sa.Column(
            "external_synset_id",
            sa.String(length=200),
            nullable=True,
        ),
    )

    op.drop_constraint(
        op.f("uq_word_senses_word_concept"),
        "word_senses",
        type_="unique",
    )

    # Existing development data may contain duplicate source locators
    # because the old schema did not enforce source_id + source_locator
    # uniqueness. Keep the lowest-id row and remove later duplicates
    # before adding the new constraint.
    op.execute(
        """
        WITH ranked_word_senses AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY source_id, source_locator
                    ORDER BY
                        CASE review_status
                            WHEN 'reviewed' THEN 0
                            WHEN 'unreviewed' THEN 1
                            WHEN 'rejected' THEN 2
                            ELSE 3
                        END,
                        CASE confidence
                            WHEN 'high' THEN 0
                            WHEN 'medium' THEN 1
                            WHEN 'low' THEN 2
                            ELSE 3
                        END,
                        id
                ) AS duplicate_rank
            FROM word_senses
            WHERE source_id IS NOT NULL
              AND source_locator IS NOT NULL
        )
        DELETE FROM word_senses
        WHERE id IN (
            SELECT id
            FROM ranked_word_senses
            WHERE duplicate_rank > 1
        )
        """
    )

    op.create_unique_constraint(
        "uq_word_senses_source_locator",
        "word_senses",
        ["source_id", "source_locator"],
    )

    op.create_check_constraint(
        "ck_word_senses_equivalence_type",
        "word_senses",
        (
            "equivalence_type IN "
            "('canonical', 'direct_equivalent', 'near_equivalent', "
            "'related', 'symbolic', 'technical', 'archaic', 'poetic')"
        ),
    )

    op.create_check_constraint(
        "ck_word_senses_sense_rank",
        "word_senses",
        "sense_rank >= 1",
    )

    op.create_index(
        "ix_word_senses_external_synset_id",
        "word_senses",
        ["external_synset_id"],
        unique=False,
    )

    op.create_index(
        "ix_word_senses_external_sense_id",
        "word_senses",
        ["external_sense_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('uq_words_language_normalized_text_pos', 'words', type_='unique')
    op.drop_index('ix_words_external_entry_id', table_name='words')
    op.create_unique_constraint(op.f('uq_words_language_normalized_text'), 'words', ['language_id', 'normalized_text'], postgresql_nulls_not_distinct=False)
    op.drop_column('words', 'external_entry_id')
    op.drop_constraint('uq_word_senses_source_locator', 'word_senses', type_='unique')
    op.drop_index('ix_word_senses_external_synset_id', table_name='word_senses')
    op.drop_index('ix_word_senses_external_sense_id', table_name='word_senses')
    op.create_unique_constraint(op.f('uq_word_senses_word_concept'), 'word_senses', ['word_id', 'concept_id'], postgresql_nulls_not_distinct=False)
    op.alter_column('word_senses', 'gloss',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=300),
               existing_nullable=False)
    op.drop_column('word_senses', 'external_synset_id')
    op.drop_column('word_senses', 'external_sense_id')
    op.drop_column('word_senses', 'sense_rank')
    op.drop_column('word_senses', 'equivalence_type')
    op.drop_constraint(None, 'concepts', type_='foreignkey')
    op.drop_constraint('uq_concepts_external_source_concept_id', 'concepts', type_='unique')
    op.drop_index('ix_concepts_concept_type', table_name='concepts')
    op.drop_column('concepts', 'external_concept_id')
    op.drop_column('concepts', 'external_source_id')
    op.drop_column('concepts', 'is_public')
    op.drop_column('concepts', 'concept_type')
    op.drop_index('ix_concept_mappings_target_concept_id', table_name='concept_mappings')
    op.drop_index('ix_concept_mappings_source_concept_id', table_name='concept_mappings')
    op.drop_table('concept_mappings')
    # ### end Alembic commands ###
