from app.schemas.generate import GeneratedNameResponse, NamePartResponse


mock_generated_names = [
    GeneratedNameResponse(
        id="auravel",
        name="Auravel",
        category="generated",
        meaning="Dawn and openness",
        language="Generated",
        sourceLanguages=["Latin"],
        flavors=["default", "fantasy", "ancient-inspired"],
        explanation=(
            "A newly crafted name combining imagery of dawn "
            "with a light, open-sounding ending."
        ),
        parts=[
            NamePartResponse(
                text="aur-",
                meaning="Dawn, glow, or golden light",
                language="Latin-inspired",
                kind="inspired",
                note="Inspired by words such as aurora.",
            ),
            NamePartResponse(
                text="-avel",
                meaning="Open, airy, flowing sound",
                language="Crafted",
                kind="crafted",
                note="An invented ending added for style and rhythm.",
            ),
        ],
    ),
    GeneratedNameResponse(
        id="lucira",
        name="Lucira",
        category="generated",
        meaning="Light and clarity",
        language="Generated",
        sourceLanguages=["Latin"],
        flavors=["default", "fantasy", "modern"],
        explanation=(
            "A newly crafted name built around a root "
            "associated with light."
        ),
        parts=[
            NamePartResponse(
                text="luc-",
                meaning="Light or brightness",
                language="Latin",
                kind="root",
                note="Related to the Latin word lux.",
            ),
            NamePartResponse(
                text="-ira",
                meaning="Soft, name-like ending",
                language="Crafted",
                kind="crafted",
                note="An invented ending added for rhythm.",
            ),
        ],
    ),
    GeneratedNameResponse(
        id="photel",
        name="Photel",
        category="generated",
        meaning="Light",
        language="Generated",
        sourceLanguages=["Greek"],
        flavors=["ancient-inspired"],
        explanation=(
            "A compact generated name built around "
            "a Greek root associated with light."
        ),
        parts=[
            NamePartResponse(
                text="phot-",
                meaning="Light",
                language="Greek",
                kind="root",
                note="Connected to Greek-derived words associated with light.",
            ),
            NamePartResponse(
                text="-el",
                meaning="Compact name-like ending",
                language="Crafted",
                kind="crafted",
                note="An invented ending added for rhythm.",
            ),
        ],
    ),
]