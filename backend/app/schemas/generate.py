from typing import Literal

from pydantic import BaseModel, Field, model_validator


GenerationFlavor = Literal[
    "default",
    "fantasy",
    "ancient-inspired",
    "modern",
]

NamePartKind = Literal[
    "root",
    "word",
    "inspired",
    "crafted",
]


class GenerateRequest(BaseModel):
    meanings: list[str] = Field(min_length=1)
    language: str | None = None
    minLength: int = Field(default=0, ge=0, le=30)
    maxLength: int = Field(default=30, ge=0, le=30)
    flavor: GenerationFlavor = "default"

    @model_validator(mode="after")
    def validate_length_range(self):
        if self.minLength > self.maxLength:
            raise ValueError("minLength cannot be greater than maxLength")

        return self


class NamePartResponse(BaseModel):
    text: str
    meaning: str
    language: str
    kind: NamePartKind
    note: str | None = None


class GeneratedNameResponse(BaseModel):
    id: str
    name: str
    category: Literal["generated"]
    meaning: str
    language: Literal["Generated"]
    explanation: str
    sourceLanguages: list[str]
    flavors: list[GenerationFlavor]
    parts: list[NamePartResponse]