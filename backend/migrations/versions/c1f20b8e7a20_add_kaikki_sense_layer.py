"""add kaikki sense layer

Revision ID: c1f20b8e7a20
Revises: be6018d77f36
Create Date: 2026-06-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision: str = "c1f20b8e7a20"
down_revision: Union[str, Sequence[str], None] = "be6018d77f36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "lexemes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("language_id", sa.Integer(), nullable=False),
        sa.Column("lemma", sa.String(length=300), nullable=False),
        sa.Column("normalized_lemma", sa.String(length=300), nullable=False),
        sa.Column("part_of_speech", sa.String(length=80), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_entry_id", sa.String(length=300), nullable=True),
        sa.Column("raw_language_name", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["language_id"], ["languages.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.UniqueConstraint(
            "language_id",
            "normalized_lemma",
            "part_of_speech",
            "source_id",
            name="uq_lexemes_language_lemma_pos_source",
        ),
    )
    op.create_index(
        "ix_lexemes_normalized_lemma",
        "lexemes",
        ["normalized_lemma"],
    )
    op.create_index(
        "ix_lexemes_language_pos",
        "lexemes",
        ["language_id", "part_of_speech"],
    )

    op.create_table(
        "sense_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lexeme_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_locator", sa.Text(), nullable=False),
        sa.Column("raw_gloss", sa.Text(), nullable=False),
        sa.Column("clean_gloss", sa.Text(), nullable=False),
        sa.Column("raw_tags", sa.JSON(), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("examples", sa.JSON(), nullable=False),
        sa.Column("etymology_text", sa.Text(), nullable=True),
        sa.Column(
            "review_status",
            sa.String(length=30),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column(
            "review_tier",
            sa.String(length=30),
            nullable=False,
            server_default="human_review",
        ),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default="50",
        ),
        sa.Column(
            "review_reason",
            sa.String(length=120),
            nullable=False,
            server_default="normal_candidate",
        ),
        sa.Column(
            "notes",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["lexeme_id"],
            ["lexemes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.UniqueConstraint(
            "source_id",
            "source_locator",
            name="uq_sense_candidates_source_locator",
        ),
        sa.CheckConstraint(
            (
                "review_status IN "
                "('pending_review', 'auto_accepted', 'reviewed', "
                "'rejected', 'hidden', 'deferred', 'needs_edit', "
                "'duplicate', 'merged')"
            ),
            name="ck_sense_candidates_review_status",
        ),
        sa.CheckConstraint(
            "review_tier IN ('auto_usable', 'human_review', 'low_priority')",
            name="ck_sense_candidates_review_tier",
        ),
    )
    op.create_index(
        "ix_sense_candidates_status_priority",
        "sense_candidates",
        ["review_status", "priority"],
    )
    op.create_index(
        "ix_sense_candidates_tier_status",
        "sense_candidates",
        ["review_tier", "review_status"],
    )

    op.create_table(
        "usable_senses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lexeme_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=300), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("short_definition", sa.String(length=500), nullable=False),
        sa.Column(
            "usage_status",
            sa.String(length=30),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "review_status",
            sa.String(length=30),
            nullable=False,
            server_default="auto_accepted",
        ),
        sa.Column(
            "confidence",
            sa.String(length=20),
            nullable=False,
            server_default="medium",
        ),
        sa.Column(
            "is_name_useful",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "is_root_useful",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["lexeme_id"],
            ["lexemes.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "usage_status IN ('active', 'hidden', 'retired')",
            name="ck_usable_senses_usage_status",
        ),
        sa.CheckConstraint(
            "review_status IN ('auto_accepted', 'reviewed', 'needs_edit')",
            name="ck_usable_senses_review_status",
        ),
        sa.CheckConstraint(
            "confidence IN ('high', 'medium', 'low')",
            name="ck_usable_senses_confidence",
        ),
    )
    op.create_index(
        "ix_usable_senses_status",
        "usable_senses",
        ["usage_status", "review_status"],
    )

    op.create_table(
        "usable_sense_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usable_sense_id", sa.Integer(), nullable=False),
        sa.Column("sense_candidate_id", sa.Integer(), nullable=False),
        sa.Column(
            "support_type",
            sa.String(length=40),
            nullable=False,
            server_default="primary",
        ),
        sa.ForeignKeyConstraint(
            ["usable_sense_id"],
            ["usable_senses.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sense_candidate_id"],
            ["sense_candidates.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "usable_sense_id",
            "sense_candidate_id",
            name="uq_usable_sense_sources_pair",
        ),
        sa.CheckConstraint(
            "support_type IN ('primary', 'secondary', 'merged_from')",
            name="ck_usable_sense_sources_support_type",
        ),
    )

    op.create_table(
        "semantic_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("normalized_label", sa.String(length=120), nullable=False),
        sa.Column(
            "category",
            sa.String(length=80),
            nullable=False,
            server_default="general",
        ),
        sa.UniqueConstraint(
            "normalized_label",
            name="uq_semantic_tags_normalized_label",
        ),
    )

    op.create_table(
        "usable_sense_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usable_sense_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column(
            "weight",
            sa.Float(),
            nullable=False,
            server_default="1.0",
        ),
        sa.Column(
            "source",
            sa.String(length=40),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "review_status",
            sa.String(length=30),
            nullable=False,
            server_default="reviewed",
        ),
        sa.ForeignKeyConstraint(
            ["usable_sense_id"],
            ["usable_senses.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["semantic_tags.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "usable_sense_id",
            "tag_id",
            name="uq_usable_sense_tags_pair",
        ),
        sa.CheckConstraint(
            "weight >= 0 AND weight <= 1",
            name="ck_usable_sense_tags_weight",
        ),
    )

    op.create_table(
        "sense_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usable_sense_id", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("embedded_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["usable_sense_id"],
            ["usable_senses.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "usable_sense_id",
            "embedding_model",
            name="uq_sense_embeddings_sense_model",
        ),
    )
    op.create_index(
        "ix_sense_embeddings_model",
        "sense_embeddings",
        ["embedding_model"],
    )

    op.create_index(
        "ix_sense_embeddings_embedding_hnsw",
        "sense_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sense_embeddings_embedding_hnsw",
        table_name="sense_embeddings",
    )
    op.drop_index(
        "ix_sense_embeddings_model",
        table_name="sense_embeddings",
    )
    op.drop_table("sense_embeddings")
    op.drop_table("usable_sense_tags")
    op.drop_table("semantic_tags")
    op.drop_table("usable_sense_sources")
    op.drop_index(
        "ix_usable_senses_status",
        table_name="usable_senses",
    )
    op.drop_table("usable_senses")
    op.drop_index(
        "ix_sense_candidates_tier_status",
        table_name="sense_candidates",
    )
    op.drop_index(
        "ix_sense_candidates_status_priority",
        table_name="sense_candidates",
    )
    op.drop_table("sense_candidates")
    op.drop_index(
        "ix_lexemes_language_pos",
        table_name="lexemes",
    )
    op.drop_index(
        "ix_lexemes_normalized_lemma",
        table_name="lexemes",
    )
    op.drop_table("lexemes")