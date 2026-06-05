from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


app = FastAPI(
    title="Namecraft API",
    description="Backend API for searching and generating names by meaning.",
)


# Allow your Next.js frontend to communicate with this backend
# while both are running locally.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    min_length: int = Field(default=0, ge=0, le=30)
    max_length: int = Field(default=30, ge=0, le=30)
    flavor: GenerationFlavor = "default"


class NamePart(BaseModel):
    text: str
    meaning: str
    language: str
    kind: NamePartKind
    note: str | None = None


class GeneratedNameResult(BaseModel):
    id: str
    name: str
    category: Literal["generated"]
    meaning: str
    language: Literal["Generated"]
    explanation: str
    source_languages: list[str]
    flavors: list[GenerationFlavor]
    parts: list[NamePart]


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/generate", response_model=list[GeneratedNameResult])
def generate_names(request: GenerateRequest):
    mock_results = [
        GeneratedNameResult(
            id="auravel",
            name="Auravel",
            category="generated",
            meaning="Dawn and openness",
            language="Generated",
            explanation=(
                "A newly crafted name combining imagery of dawn "
                "with a light, open-sounding ending."
            ),
            source_languages=["Latin"],
            flavors=["default", "fantasy", "ancient-inspired"],
            parts=[
                NamePart(
                    text="aur-",
                    meaning="Dawn, glow, or golden light",
                    language="Latin-inspired",
                    kind="inspired",
                    note="Inspired by words such as aurora.",
                ),
                NamePart(
                    text="-avel",
                    meaning="Open, airy, flowing sound",
                    language="Crafted",
                    kind="crafted",
                    note="An invented ending added for style and rhythm.",
                ),
            ],
        ),
        GeneratedNameResult(
            id="lucira",
            name="Lucira",
            category="generated",
            meaning="Light and clarity",
            language="Generated",
            explanation=(
                "A newly crafted name built around a root "
                "associated with light."
            ),
            source_languages=["Latin"],
            flavors=["default", "fantasy", "modern"],
            parts=[
                NamePart(
                    text="luc-",
                    meaning="Light or brightness",
                    language="Latin",
                    kind="root",
                    note="Related to the Latin word lux.",
                ),
                NamePart(
                    text="-ira",
                    meaning="Soft, name-like ending",
                    language="Crafted",
                    kind="crafted",
                    note="An invented ending added for rhythm.",
                ),
            ],
        ),
        GeneratedNameResult(
            id="photel",
            name="Photel",
            category="generated",
            meaning="Light",
            language="Generated",
            explanation=(
                "A compact generated name built around "
                "a Greek root associated with light."
            ),
            source_languages=["Greek"],
            flavors=["ancient-inspired"],
            parts=[
                NamePart(
                    text="phot-",
                    meaning="Light",
                    language="Greek",
                    kind="root",
                    note="Connected to Greek-derived words associated with light.",
                ),
                NamePart(
                    text="-el",
                    meaning="Compact name-like ending",
                    language="Crafted",
                    kind="crafted",
                    note="An invented ending added for rhythm.",
                ),
            ],
        ),
    ]

    return [
        result
        for result in mock_results
        if (
            request.min_length <= len(result.name) <= request.max_length
            and (
                request.language is None
                or request.language in result.source_languages
            )
            and request.flavor in result.flavors
        )
    ]