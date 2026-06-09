# backend/app/models/semantic.py

from sqlalchemy import Boolean, Column, Float, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# Shared semantic infrastructure
class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    license: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Concept(Base):
    __tablename__ = "concepts"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

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