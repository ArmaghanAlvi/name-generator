from typing import Literal

from pydantic import BaseModel, Field


class ExploreRequest(BaseModel):
    meanings: list[str] = Field(min_length=1)
    expansionCount: int = Field(default=0, ge=0, le=10)
    language: str | None = None
    minLength: int = Field(default=0, ge=0, le=30)
    maxLength: int = Field(default=30, ge=0, le=30)


class ExpandedConceptResponse(BaseModel):
    slug: str
    label: str
    relationshipType: str
    weight: float


class ResultResponse(BaseModel):
    id: str
    name: str
    category: Literal[
        "established",
        "related",
        "translation",
        "root",
        "generated",
    ]
    meaning: str
    language: str
    explanation: str
    matchType: Literal["exact", "expanded"]
    matchedConcept: str

    relationshipType: str | None = None
    relationshipWeight: float | None = None
    equivalenceType: str | None = None
    senseRank: int | None = None
    source: str | None = None
    sourceLocator: str | None = None
    confidence: str | None = None

    sourceLanguages: list[str] | None = None
    flavors: list[str] | None = None
    parts: list[dict] | None = None


class ExploreResponse(BaseModel):
    matchedConcepts: list[str]
    expandedConcepts: list[ExpandedConceptResponse]
    results: list[ResultResponse]