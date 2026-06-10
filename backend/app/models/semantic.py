from typing import TYPE_CHECKING

from sqlalchemy import Column, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.generated_name import GeneratedName, Language



class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    license: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    words: Mapped[list["Word"]] = relationship(
        back_populates="source",
    )

    established_names: Mapped[list["EstablishedName"]] = relationship(
        back_populates="source",
    )

    roots: Mapped[list["Root"]] = relationship(
        back_populates="source",
    )


class Concept(Base):
    __tablename__ = "concepts"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    weight: Mapped[float] = mapped_column(nullable=False)

    source_concept: Mapped["Concept"] = relationship(
        foreign_keys=[source_concept_id],
        back_populates="outgoing_relationships",
    )

    target_concept: Mapped["Concept"] = relationship(
        foreign_keys=[target_concept_id],
        back_populates="incoming_relationships",
    )


# Yellow-card models
class Word(Base):
    __tablename__ = "words"

    id: Mapped[int] = mapped_column(primary_key=True)

    language_id: Mapped[int] = mapped_column(
        ForeignKey("languages.id"),
        nullable=False,
    )

    text: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_text: Mapped[str] = mapped_column(String(200), nullable=False)
    transliteration: Mapped[str | None] = mapped_column(String(200))
    part_of_speech: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))

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

    gloss: Mapped[str] = mapped_column(String(300), nullable=False)
    is_primary: Mapped[bool] = mapped_column(default=True, nullable=False)

    word: Mapped["Word"] = relationship(
        back_populates="senses",
    )

    concept: Mapped["Concept"] = relationship(
        back_populates="word_senses",
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