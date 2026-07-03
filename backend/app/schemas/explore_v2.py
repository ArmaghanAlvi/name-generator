from typing import Literal

from pydantic import BaseModel, Field


class ExploreV2Request(BaseModel):
    selectedSenseIds: list[int] = Field(min_length=1)
    queryText: str = ""
    expansionCount: int = Field(default=10, ge=0, le=100)
    language: str | None = None
    minLength: int = Field(default=0, ge=0, le=30)
    maxLength: int = Field(default=30, ge=0, le=30)
    # Multi-hop controls. depth=1 => single-hop (existing behavior); width
    # defaults to None so callers that only send expansionCount are unchanged.
    width: int | None = Field(default=None, ge=0, le=10)
    depth: int = Field(default=1, ge=0, le=3)


class HopPathStep(BaseModel):
    word: str
    senseId: int
    depth: int


class ExploreV2Result(BaseModel):
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
    matchedSenseId: int
    relationshipType: str
    relationshipWeight: float
    partOfSpeech: str
    # Multi-hop metadata. Optional so single-hop results (depth=1) omit them.
    depth: int = 0
    parentSenseId: int | None = None
    provenance: str | None = None
    path: list[HopPathStep] = Field(default_factory=list)


class ExpandedSenseResponse(BaseModel):
    senseId: int
    word: str
    language: str
    definition: str
    relationshipType: str
    weight: float


class ExploreV2Response(BaseModel):
    selectedSenseIds: list[int]
    expandedSenses: list[ExpandedSenseResponse]
    results: list[ExploreV2Result]