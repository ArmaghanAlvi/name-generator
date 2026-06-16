from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
)
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