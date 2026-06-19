"""add no-review Kaikki sense layer

Revision ID: c1f20b8e7a20
Revises: be6018d77f36
Create Date: 2026-06-19

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
        sa.Column("source_entry_id", sa.String(length=500), nullable=False),
        sa.Column("raw_language_name", sa.String(length=120), nullable=True),
        sa.Column("raw_entry", sa.JSON(), nullable=False),
        sa.Column(
            "import_status",
            sa.String(length=30),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["language_id"], ["languages.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.UniqueConstraint(
            "source_id",
            "source_entry_id",
            name="uq_lexemes_source_entry_id",
        ),
        sa.CheckConstraint(
            "import_status IN ('active', 'retired')",
            name="ck_lexemes_import_status",
        ),
    )
    op.create_index(
        "ix_lexemes_normalized_lemma",
        "lexemes",
        ["normalized_lemma"],
    )
    op.create_index(
        "ix_lexemes_language_lemma",
        "lexemes",
        ["language_id", "normalized_lemma"],
    )
    op.create_index(
        "ix_lexemes_language_pos",
        "lexemes",
        ["language_id", "part_of_speech"],
    )

    op.create_table(
        "senses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lexeme_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_locator", sa.Text(), nullable=False),
        sa.Column("sense_index", sa.Integer(), nullable=False),
        sa.Column(
            "source_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "definition",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column("raw_glosses", sa.JSON(), nullable=False),
        sa.Column("raw_tags", sa.JSON(), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("examples", sa.JSON(), nullable=False),
        sa.Column("raw_sense", sa.JSON(), nullable=False),
        sa.Column("etymology_text", sa.Text(), nullable=True),
        sa.Column(
            "visibility_status",
            sa.String(length=30),
            nullable=False,
            server_default="visible",
        ),
        sa.Column(
            "admin_status",
            sa.String(length=30),
            nullable=False,
            server_default="normal",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
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
            name="uq_senses_source_locator",
        ),
        sa.CheckConstraint(
            "visibility_status IN ('visible', 'hidden')",
            name="ck_senses_visibility_status",
        ),
        sa.CheckConstraint(
            "admin_status IN ('normal', 'edited', 'merged', 'suppressed')",
            name="ck_senses_admin_status",
        ),
    )
    op.create_index(
        "ix_senses_lexeme_id",
        "senses",
        ["lexeme_id"],
    )
    op.create_index(
        "ix_senses_visibility_status",
        "senses",
        ["visibility_status"],
    )

    op.create_table(
        "sense_selection_stats",
        sa.Column("sense_id", sa.Integer(), primary_key=True),
        sa.Column(
            "selection_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "last_selected_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["sense_id"],
            ["senses.id"],
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "sense_selection_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sense_id", sa.Integer(), nullable=False),
        sa.Column(
            "query_text",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "selected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["sense_id"],
            ["senses.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_sense_selection_events_sense_id",
        "sense_selection_events",
        ["sense_id"],
    )

    op.create_table(
        "sense_admin_overrides",
        sa.Column("sense_id", sa.Integer(), primary_key=True),
        sa.Column(
            "is_hidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("pinned_rank", sa.Integer(), nullable=True),
        sa.Column("label_override", sa.String(length=300), nullable=True),
        sa.Column("definition_override", sa.Text(), nullable=True),
        sa.Column(
            "notes",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["sense_id"],
            ["senses.id"],
            ondelete="CASCADE",
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
        "sense_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sense_id", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["sense_id"],
            ["senses.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["semantic_tags.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "sense_id",
            "tag_id",
            name="uq_sense_tags_pair",
        ),
        sa.CheckConstraint(
            "weight >= 0 AND weight <= 1",
            name="ck_sense_tags_weight",
        ),
    )

    op.create_table(
        "sense_embeddings",
        sa.Column("sense_id", sa.Integer(), primary_key=True),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("embedded_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["sense_id"],
            ["senses.id"],
            ondelete="CASCADE",
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
    op.drop_table("sense_tags")
    op.drop_table("semantic_tags")
    op.drop_table("sense_admin_overrides")
    op.drop_index(
        "ix_sense_selection_events_sense_id",
        table_name="sense_selection_events",
    )
    op.drop_table("sense_selection_events")
    op.drop_table("sense_selection_stats")
    op.drop_index(
        "ix_senses_visibility_status",
        table_name="senses",
    )
    op.drop_index(
        "ix_senses_lexeme_id",
        table_name="senses",
    )
    op.drop_table("senses")
    op.drop_index(
        "ix_lexemes_language_pos",
        table_name="lexemes",
    )
    op.drop_index(
        "ix_lexemes_language_lemma",
        table_name="lexemes",
    )
    op.drop_index(
        "ix_lexemes_normalized_lemma",
        table_name="lexemes",
    )
    op.drop_table("lexemes")