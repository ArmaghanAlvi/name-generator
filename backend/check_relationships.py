from app.models.generated_name import GeneratedName, Language, NamePart
from app.models.semantic import (
    Concept,
    ConceptAlias,
    ConceptRelationship,
    EstablishedName,
    NameMeaning,
    NameRelationship,
    Root,
    RootMeaning,
    Source,
    Word,
    WordSense,
)

checks = {
    Language: [
        "generated_names",
        "words",
        "established_names",
        "roots",
    ],
    GeneratedName: [
        "source_languages",
        "flavors",
        "parts",
        "concepts",
    ],
    NamePart: [
        "generated_name",
    ],
    Source: [
        "words",
        "established_names",
        "roots",
    ],
    Concept: [
        "aliases",
        "outgoing_relationships",
        "incoming_relationships",
        "word_senses",
        "name_meanings",
        "root_meanings",
        "generated_names",
    ],
    ConceptAlias: [
        "concept",
    ],
    ConceptRelationship: [
        "source_concept",
        "target_concept",
    ],
    Word: [
        "language",
        "source",
        "senses",
    ],
    WordSense: [
        "word",
        "concept",
    ],
    EstablishedName: [
        "language",
        "source",
        "meanings",
        "outgoing_relationships",
        "incoming_relationships",
    ],
    NameMeaning: [
        "established_name",
        "concept",
    ],
    NameRelationship: [
        "source_name",
        "target_name",
    ],
    Root: [
        "language",
        "source",
        "meanings",
    ],
    RootMeaning: [
        "root",
        "concept",
    ],
}

all_present = True

for model, attributes in checks.items():
    missing = [
        attribute
        for attribute in attributes
        if not hasattr(model, attribute)
    ]

    if missing:
        all_present = False
        print(f"{model.__name__}: missing {missing}")
    else:
        print(f"{model.__name__}: OK")

if all_present:
    print("\nAll expected ORM relationship attributes are present.")