from typing import Literal

from pydantic import BaseModel, Field


class ExploreV2Request(BaseModel):
    selectedSenseIds: list[int] = Field(min_length=1)
    queryText: str = ""
    expansionCount: int = Field(default=10, ge=0, le=100)
    language: str | None = None
    minLength: int = Field(default=0, ge=0, le=30)
    maxLength: int = Field(default=30, ge=0, le=30)


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