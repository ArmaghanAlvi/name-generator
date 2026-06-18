from typing import TYPE_CHECKING
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)

from pgvector.sqlalchemy import Vector

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.generated_name import GeneratedName, Language



class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Nullable temporarily so the existing development seed row
    # can survive the migration.
    slug: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    source_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    license: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "slug",
            name="uq_sources_slug",
        ),
    )

    words: Mapped[list["Word"]] = relationship(
        back_populates="source",
    )

    established_names: Mapped[list["EstablishedName"]] = relationship(
        back_populates="source",
    )

    roots: Mapped[list["Root"]] = relationship(
        back_populates="source",
    )

    concept_relationships: Mapped[list["ConceptRelationship"]] = relationship(
        back_populates="source",
    )

    word_senses: Mapped[list["WordSense"]] = relationship(
        back_populates="source",
    )

    external_concepts: Mapped[list["Concept"]] = relationship(
        back_populates="external_source",
        foreign_keys="Concept.external_source_id",
    )

    concept_mappings: Mapped[list["ConceptMapping"]] = relationship(
        back_populates="source",
    )


class Concept(Base):
    __tablename__ = "concepts"

    id: Mapped[int] = mapped_column(primary_key=True)

    slug: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    label: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    domain: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="active",
        nullable=False,
    )

    concept_type: Mapped[str] = mapped_column(
        String(50),
        default="curated",
        nullable=False,
    )

    is_public: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    external_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id"),
        nullable=True,
    )

    external_concept_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    external_source: Mapped["Source | None"] = relationship(
        back_populates="external_concepts",
        foreign_keys=[external_source_id],
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'draft', 'retired')",
            name="ck_concepts_status",
        ),
        CheckConstraint(
            (
                "concept_type IN "
                "('curated', 'external_synset', "
                "'imported_candidate', 'merged', 'retired')"
            ),
            name="ck_concepts_concept_type",
        ),
        UniqueConstraint(
            "external_source_id",
            "external_concept_id",
            name="uq_concepts_external_source_concept_id",
        ),
        Index(
            "ix_concepts_concept_type",
            "concept_type",
        ),
    )

    aliases: Mapped[list["ConceptAlias"]] = relationship(
        back_populates="concept",
        cascade="all, delete-orphan",
    )

    outgoing_relationships: Mapped[list["ConceptRelationship"]] = relationship(
        foreign_keys="ConceptRelationship.source_concept_id",
        back_populates="source_concept",
        cascade="all, delete-orphan",
    )

    incoming_relationships: Mapped[list["ConceptRelationship"]] = relationship(
        foreign_keys="ConceptRelationship.target_concept_id",
        back_populates="target_concept",
    )

    outgoing_mappings: Mapped[list["ConceptMapping"]] = relationship(
        foreign_keys="ConceptMapping.source_concept_id",
        back_populates="source_concept",
        cascade="all, delete-orphan",
    )

    incoming_mappings: Mapped[list["ConceptMapping"]] = relationship(
        foreign_keys="ConceptMapping.target_concept_id",
        back_populates="target_concept",
    )

    word_senses: Mapped[list["WordSense"]] = relationship(
        back_populates="concept",
    )

    name_meanings: Mapped[list["NameMeaning"]] = relationship(
        back_populates="concept",
    )

    root_meanings: Mapped[list["RootMeaning"]] = relationship(
        back_populates="concept",
    )

    generated_names: Mapped[list["GeneratedName"]] = relationship(
        secondary="generated_name_concepts",
        back_populates="concepts",
    )


class ConceptAlias(Base):
    __tablename__ = "concept_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)

    concept_id: Mapped[int] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
    )

    text: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_text: Mapped[str] = mapped_column(String(200), nullable=False)

    concept: Mapped["Concept"] = relationship(
        back_populates="aliases",
    )

    __table_args__ = (
        UniqueConstraint(
            "concept_id",
            "normalized_text",
            name="uq_concept_aliases_concept_normalized_text",
        ),
        Index(
            "ix_concept_aliases_normalized_text",
            "normalized_text",
        ),
    )


class ConceptRelationship(Base):
    __tablename__ = "concept_relationships"

    id: Mapped[int] = mapped_column(primary_key=True)

    source_concept_id: Mapped[int] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
    )

    target_concept_id: Mapped[int] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
    )

    relationship_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    weight: Mapped[float] = mapped_column(
        nullable=False,
    )

    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id"),
        nullable=True,
    )

    source_locator: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    confidence: Mapped[str] = mapped_column(
        String(20),
        default="medium",
        nullable=False,
    )

    review_status: Mapped[str] = mapped_column(
        String(20),
        default="unreviewed",
        nullable=False,
    )

    source_concept: Mapped["Concept"] = relationship(
        foreign_keys=[source_concept_id],
        back_populates="outgoing_relationships",
    )

    target_concept: Mapped["Concept"] = relationship(
        foreign_keys=[target_concept_id],
        back_populates="incoming_relationships",
    )

    source: Mapped["Source | None"] = relationship(
        back_populates="concept_relationships",
    )

    __table_args__ = (
        UniqueConstraint(
            "source_concept_id",
            "target_concept_id",
            "relationship_type",
            name="uq_concept_relationships_source_target_type",
        ),
        CheckConstraint(
            "weight >= 0 AND weight <= 1",
            name="ck_concept_relationships_weight_range",
        ),
        CheckConstraint(
            "confidence IN ('high', 'medium', 'low')",
            name="ck_concept_relationships_confidence",
        ),
        CheckConstraint(
            "review_status IN ('unreviewed', 'reviewed', 'rejected')",
            name="ck_concept_relationships_review_status",
        ),
        Index(
            "ix_concept_relationships_source_concept_id",
            "source_concept_id",
        ),
        Index(
            "ix_concept_relationships_target_concept_id",
            "target_concept_id",
        ),
    )


class ConceptMapping(Base):
    __tablename__ = "concept_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)

    source_concept_id: Mapped[int] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
    )

    target_concept_id: Mapped[int] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
    )

    mapping_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    weight: Mapped[float] = mapped_column(
        default=1.0,
        nullable=False,
    )

    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id"),
        nullable=True,
    )

    source_locator: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    confidence: Mapped[str] = mapped_column(
        String(20),
        default="medium",
        nullable=False,
    )

    review_status: Mapped[str] = mapped_column(
        String(20),
        default="unreviewed",
        nullable=False,
    )

    source_concept: Mapped["Concept"] = relationship(
        foreign_keys=[source_concept_id],
        back_populates="outgoing_mappings",
    )

    target_concept: Mapped["Concept"] = relationship(
        foreign_keys=[target_concept_id],
        back_populates="incoming_mappings",
    )

    source: Mapped["Source | None"] = relationship(
        back_populates="concept_mappings",
    )

    __table_args__ = (
        UniqueConstraint(
            "source_concept_id",
            "target_concept_id",
            "mapping_type",
            name="uq_concept_mappings_source_target_type",
        ),
        CheckConstraint(
            "weight >= 0 AND weight <= 1",
            name="ck_concept_mappings_weight_range",
        ),
        CheckConstraint(
            "mapping_type IN ('exact', 'near', 'broader', 'narrower', 'related')",
            name="ck_concept_mappings_mapping_type",
        ),
        CheckConstraint(
            "confidence IN ('high', 'medium', 'low')",
            name="ck_concept_mappings_confidence",
        ),
        CheckConstraint(
            "review_status IN ('unreviewed', 'reviewed', 'rejected')",
            name="ck_concept_mappings_review_status",
        ),
        Index(
            "ix_concept_mappings_source_concept_id",
            "source_concept_id",
        ),
        Index(
            "ix_concept_mappings_target_concept_id",
            "target_concept_id",
        ),
    )


# Yellow-card models
class Word(Base):
    __tablename__ = "words"

    id: Mapped[int] = mapped_column(primary_key=True)

    language_id: Mapped[int] = mapped_column(
        ForeignKey("languages.id"),
        nullable=False,
    )

    text: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    normalized_text: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    transliteration: Mapped[str | None] = mapped_column(
        String(200),
    )

    part_of_speech: Mapped[str | None] = mapped_column(
        String(50),
    )

    external_entry_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
    )

    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id"),
    )

    language: Mapped["Language"] = relationship(
        back_populates="words",
    )

    source: Mapped["Source | None"] = relationship(
        back_populates="words",
    )

    senses: Mapped[list["WordSense"]] = relationship(
        back_populates="word",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "language_id",
            "normalized_text",
            "part_of_speech",
            name="uq_words_language_normalized_text_pos",
        ),
        Index(
            "ix_words_language_id",
            "language_id",
        ),
        Index(
            "ix_words_external_entry_id",
            "external_entry_id",
        ),
    )


class WordSense(Base):
    __tablename__ = "word_senses"

    id: Mapped[int] = mapped_column(primary_key=True)

    word_id: Mapped[int] = mapped_column(
        ForeignKey("words.id", ondelete="CASCADE"),
        nullable=False,
    )

    concept_id: Mapped[int] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
    )

    gloss: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    is_primary: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
    )

    equivalence_type: Mapped[str] = mapped_column(
        String(50),
        default="direct_equivalent",
        nullable=False,
    )

    sense_rank: Mapped[int] = mapped_column(
        default=1,
        nullable=False,
    )

    external_sense_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    external_synset_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id"),
        nullable=True,
    )

    source_locator: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    confidence: Mapped[str] = mapped_column(
        String(20),
        default="medium",
        nullable=False,
    )

    review_status: Mapped[str] = mapped_column(
        String(20),
        default="unreviewed",
        nullable=False,
    )

    word: Mapped["Word"] = relationship(
        back_populates="senses",
    )

    concept: Mapped["Concept"] = relationship(
        back_populates="word_senses",
    )

    source: Mapped["Source | None"] = relationship(
        back_populates="word_senses",
    )

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "source_locator",
            name="uq_word_senses_source_locator",
        ),
        CheckConstraint(
            (
                "equivalence_type IN "
                "('canonical', 'direct_equivalent', 'near_equivalent', "
                "'related', 'symbolic', 'technical', 'archaic', 'poetic')"
            ),
            name="ck_word_senses_equivalence_type",
        ),
        CheckConstraint(
            "sense_rank >= 1",
            name="ck_word_senses_sense_rank",
        ),
        CheckConstraint(
            "confidence IN ('high', 'medium', 'low')",
            name="ck_word_senses_confidence",
        ),
        CheckConstraint(
            "review_status IN ('unreviewed', 'reviewed', 'rejected')",
            name="ck_word_senses_review_status",
        ),
        Index(
            "ix_word_senses_concept_id",
            "concept_id",
        ),
        Index(
            "ix_word_senses_external_synset_id",
            "external_synset_id",
        ),
        Index(
            "ix_word_senses_external_sense_id",
            "external_sense_id",
        ),
    )


class Lexeme(Base):
    """
    A dictionary headword/lemma imported from Kaikki.

    This is intentionally separate from the older Word table.
    Word currently means "accepted word tied to a concept."
    Lexeme means "raw dictionary lemma from a source."
    """

    __tablename__ = "lexemes"

    id: Mapped[int] = mapped_column(primary_key=True)

    language_id: Mapped[int] = mapped_column(
        ForeignKey("languages.id"),
        nullable=False,
    )

    lemma: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
    )

    normalized_lemma: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
    )

    part_of_speech: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
    )

    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id"),
        nullable=False,
    )

    source_entry_id: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )

    raw_language_name: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    language: Mapped["Language"] = relationship()
    source: Mapped["Source"] = relationship()

    sense_candidates: Mapped[list["SenseCandidate"]] = relationship(
        back_populates="lexeme",
        cascade="all, delete-orphan",
    )

    usable_senses: Mapped[list["UsableSense"]] = relationship(
        back_populates="lexeme",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "language_id",
            "normalized_lemma",
            "part_of_speech",
            "source_id",
            name="uq_lexemes_language_lemma_pos_source",
        ),
        Index(
            "ix_lexemes_normalized_lemma",
            "normalized_lemma",
        ),
        Index(
            "ix_lexemes_language_pos",
            "language_id",
            "part_of_speech",
        ),
    )


class SenseCandidate(Base):
    """
    Raw or lightly cleaned sense imported from Kaikki.

    This is the review queue. Most rows should never be hand-edited.
    """

    __tablename__ = "sense_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)

    lexeme_id: Mapped[int] = mapped_column(
        ForeignKey("lexemes.id", ondelete="CASCADE"),
        nullable=False,
    )

    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id"),
        nullable=False,
    )

    source_locator: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    raw_gloss: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    clean_gloss: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    raw_tags: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
    )

    categories: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
    )

    examples: Mapped[list[dict]] = mapped_column(
        JSON,
        nullable=False,
    )

    etymology_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    review_status: Mapped[str] = mapped_column(
        String(30),
        default="pending_review",
        nullable=False,
    )

    review_tier: Mapped[str] = mapped_column(
        String(30),
        default="human_review",
        nullable=False,
    )

    priority: Mapped[int] = mapped_column(
        Integer,
        default=50,
        nullable=False,
    )

    review_reason: Mapped[str] = mapped_column(
        String(120),
        default="normal_candidate",
        nullable=False,
    )

    notes: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    lexeme: Mapped["Lexeme"] = relationship(
        back_populates="sense_candidates",
    )

    source: Mapped["Source"] = relationship()

    usable_sources: Mapped[list["UsableSenseSource"]] = relationship(
        back_populates="sense_candidate",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "source_locator",
            name="uq_sense_candidates_source_locator",
        ),
        CheckConstraint(
            (
                "review_status IN "
                "('pending_review', 'auto_accepted', 'reviewed', "
                "'rejected', 'hidden', 'deferred', 'needs_edit', "
                "'duplicate', 'merged')"
            ),
            name="ck_sense_candidates_review_status",
        ),
        CheckConstraint(
            "review_tier IN ('auto_usable', 'human_review', 'low_priority')",
            name="ck_sense_candidates_review_tier",
        ),
        Index(
            "ix_sense_candidates_status_priority",
            "review_status",
            "priority",
        ),
        Index(
            "ix_sense_candidates_tier_status",
            "review_tier",
            "review_status",
        ),
    )


class UsableSense(Base):
    """
    The meaning layer your app should actually search.

    A usable sense may be auto-created from one Kaikki candidate,
    manually accepted from one candidate, or later merged from several.
    """

    __tablename__ = "usable_senses"

    id: Mapped[int] = mapped_column(primary_key=True)

    lexeme_id: Mapped[int] = mapped_column(
        ForeignKey("lexemes.id", ondelete="CASCADE"),
        nullable=False,
    )

    label: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
    )

    definition: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    short_definition: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    usage_status: Mapped[str] = mapped_column(
        String(30),
        default="active",
        nullable=False,
    )

    review_status: Mapped[str] = mapped_column(
        String(30),
        default="auto_accepted",
        nullable=False,
    )

    confidence: Mapped[str] = mapped_column(
        String(20),
        default="medium",
        nullable=False,
    )

    is_name_useful: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    is_root_useful: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    lexeme: Mapped["Lexeme"] = relationship(
        back_populates="usable_senses",
    )

    source_links: Mapped[list["UsableSenseSource"]] = relationship(
        back_populates="usable_sense",
        cascade="all, delete-orphan",
    )

    tags: Mapped[list["UsableSenseTag"]] = relationship(
        back_populates="usable_sense",
        cascade="all, delete-orphan",
    )

    embeddings: Mapped[list["SenseEmbedding"]] = relationship(
        back_populates="usable_sense",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "usage_status IN ('active', 'hidden', 'retired')",
            name="ck_usable_senses_usage_status",
        ),
        CheckConstraint(
            "review_status IN ('auto_accepted', 'reviewed', 'needs_edit')",
            name="ck_usable_senses_review_status",
        ),
        CheckConstraint(
            "confidence IN ('high', 'medium', 'low')",
            name="ck_usable_senses_confidence",
        ),
        Index(
            "ix_usable_senses_status",
            "usage_status",
            "review_status",
        ),
    )


class UsableSenseSource(Base):
    __tablename__ = "usable_sense_sources"

    id: Mapped[int] = mapped_column(primary_key=True)

    usable_sense_id: Mapped[int] = mapped_column(
        ForeignKey("usable_senses.id", ondelete="CASCADE"),
        nullable=False,
    )

    sense_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("sense_candidates.id", ondelete="CASCADE"),
        nullable=False,
    )

    support_type: Mapped[str] = mapped_column(
        String(40),
        default="primary",
        nullable=False,
    )

    usable_sense: Mapped["UsableSense"] = relationship(
        back_populates="source_links",
    )

    sense_candidate: Mapped["SenseCandidate"] = relationship(
        back_populates="usable_sources",
    )

    __table_args__ = (
        UniqueConstraint(
            "usable_sense_id",
            "sense_candidate_id",
            name="uq_usable_sense_sources_pair",
        ),
        CheckConstraint(
            "support_type IN ('primary', 'secondary', 'merged_from')",
            name="ck_usable_sense_sources_support_type",
        ),
    )


class SemanticTag(Base):
    __tablename__ = "semantic_tags"

    id: Mapped[int] = mapped_column(primary_key=True)

    label: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    normalized_label: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    category: Mapped[str] = mapped_column(
        String(80),
        default="general",
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "normalized_label",
            name="uq_semantic_tags_normalized_label",
        ),
    )


class UsableSenseTag(Base):
    __tablename__ = "usable_sense_tags"

    id: Mapped[int] = mapped_column(primary_key=True)

    usable_sense_id: Mapped[int] = mapped_column(
        ForeignKey("usable_senses.id", ondelete="CASCADE"),
        nullable=False,
    )

    tag_id: Mapped[int] = mapped_column(
        ForeignKey("semantic_tags.id", ondelete="CASCADE"),
        nullable=False,
    )

    weight: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(40),
        default="manual",
        nullable=False,
    )

    review_status: Mapped[str] = mapped_column(
        String(30),
        default="reviewed",
        nullable=False,
    )

    usable_sense: Mapped["UsableSense"] = relationship(
        back_populates="tags",
    )

    tag: Mapped["SemanticTag"] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "usable_sense_id",
            "tag_id",
            name="uq_usable_sense_tags_pair",
        ),
        CheckConstraint(
            "weight >= 0 AND weight <= 1",
            name="ck_usable_sense_tags_weight",
        ),
    )


class SenseEmbedding(Base):
    __tablename__ = "sense_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)

    usable_sense_id: Mapped[int] = mapped_column(
        ForeignKey("usable_senses.id", ondelete="CASCADE"),
        nullable=False,
    )

    embedding_model: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    embedding_dimensions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    embedded_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    embedding: Mapped[list[float]] = mapped_column(
        Vector(384),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    usable_sense: Mapped["UsableSense"] = relationship(
        back_populates="embeddings",
    )

    __table_args__ = (
        UniqueConstraint(
            "usable_sense_id",
            "embedding_model",
            name="uq_sense_embeddings_sense_model",
        ),
        Index(
            "ix_sense_embeddings_model",
            "embedding_model",
        ),
    )


# Green-card models
class EstablishedName(Base):
    __tablename__ = "established_names"

    id: Mapped[int] = mapped_column(primary_key=True)

    language_id: Mapped[int] = mapped_column(
        ForeignKey("languages.id"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    native_script: Mapped[str | None] = mapped_column(String(200))
    transliteration: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))

    language: Mapped["Language"] = relationship(
        back_populates="established_names",
    )

    source: Mapped["Source | None"] = relationship(
        back_populates="established_names",
    )

    meanings: Mapped[list["NameMeaning"]] = relationship(
        back_populates="established_name",
        cascade="all, delete-orphan",
    )

    outgoing_relationships: Mapped[list["NameRelationship"]] = relationship(
        foreign_keys="NameRelationship.source_name_id",
        back_populates="source_name",
        cascade="all, delete-orphan",
    )

    incoming_relationships: Mapped[list["NameRelationship"]] = relationship(
        foreign_keys="NameRelationship.target_name_id",
        back_populates="target_name",
    )


class NameMeaning(Base):
    __tablename__ = "name_meanings"

    id: Mapped[int] = mapped_column(primary_key=True)

    established_name_id: Mapped[int] = mapped_column(
        ForeignKey("established_names.id", ondelete="CASCADE"),
        nullable=False,
    )

    concept_id: Mapped[int] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
    )

    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    native_form: Mapped[str | None] = mapped_column(String(200))
    is_primary: Mapped[bool] = mapped_column(default=True, nullable=False)

    established_name: Mapped["EstablishedName"] = relationship(
        back_populates="meanings",
    )

    concept: Mapped["Concept"] = relationship(
        back_populates="name_meanings",
    )


class NameRelationship(Base):
    __tablename__ = "name_relationships"

    id: Mapped[int] = mapped_column(primary_key=True)

    source_name_id: Mapped[int] = mapped_column(
        ForeignKey("established_names.id", ondelete="CASCADE"),
        nullable=False,
    )

    target_name_id: Mapped[int] = mapped_column(
        ForeignKey("established_names.id", ondelete="CASCADE"),
        nullable=False,
    )

    relationship_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    notes: Mapped[str | None] = mapped_column(Text)

    source_name: Mapped["EstablishedName"] = relationship(
        foreign_keys=[source_name_id],
        back_populates="outgoing_relationships",
    )

    target_name: Mapped["EstablishedName"] = relationship(
        foreign_keys=[target_name_id],
        back_populates="incoming_relationships",
    )


# Pink-card models
class Root(Base):
    __tablename__ = "roots"

    id: Mapped[int] = mapped_column(primary_key=True)

    language_id: Mapped[int] = mapped_column(
        ForeignKey("languages.id"),
        nullable=False,
    )

    text: Mapped[str] = mapped_column(String(200), nullable=False)
    transliteration: Mapped[str | None] = mapped_column(String(200))
    root_type: Mapped[str] = mapped_column(String(50), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))

    language: Mapped["Language"] = relationship(
        back_populates="roots",
    )

    source: Mapped["Source | None"] = relationship(
        back_populates="roots",
    )

    meanings: Mapped[list["RootMeaning"]] = relationship(
        back_populates="root",
        cascade="all, delete-orphan",
    )


class RootMeaning(Base):
    __tablename__ = "root_meanings"

    id: Mapped[int] = mapped_column(primary_key=True)

    root_id: Mapped[int] = mapped_column(
        ForeignKey("roots.id", ondelete="CASCADE"),
        nullable=False,
    )

    concept_id: Mapped[int] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
    )

    gloss: Mapped[str] = mapped_column(String(300), nullable=False)

    root: Mapped["Root"] = relationship(
        back_populates="meanings",
    )

    concept: Mapped["Concept"] = relationship(
        back_populates="root_meanings",
    )


# Blue-card semantic lookup association
generated_name_concepts = Table(
    "generated_name_concepts",
    Base.metadata,
    Column(
        "generated_name_id",
        ForeignKey("generated_names.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "concept_id",
        ForeignKey("concepts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)