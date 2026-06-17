from __future__ import annotations


REVIEW_STATUSES = {
    "pending_review",
    "reviewed",
    "rejected",
    "deferred",
    "needs_edit",
    "duplicate",
}

EXPORTABLE_STATUS = "reviewed"

CONCEPT_COLUMNS = [
    "slug",
    "label",
    "description",
    "domain",
    "status",
    "concept_type",
    "is_public",
    "external_source_slug",
    "external_concept_id",
    "review_status",
    "decision",
    "target_concept_slug",
    "notes",
]

WORD_COLUMNS = [
    "language_code",
    "text",
    "transliteration",
    "part_of_speech",
    "external_entry_id",
    "notes",
    "source_slug",
    "review_status",
]

WORD_SENSE_COLUMNS = [
    "language_code",
    "word_text",
    "part_of_speech",
    "concept_slug",
    "gloss",
    "is_primary",
    "equivalence_type",
    "sense_rank",
    "external_sense_id",
    "external_synset_id",
    "source_slug",
    "source_locator",
    "confidence",
    "review_status",
]

RELATIONSHIP_COLUMNS = [
    "source_concept_slug",
    "target_concept_slug",
    "relationship_type",
    "weight",
    "source_slug",
    "source_locator",
    "confidence",
    "review_status",
]

MAPPING_COLUMNS = [
    "source_concept_slug",
    "target_concept_slug",
    "mapping_type",
    "weight",
    "source_slug",
    "source_locator",
    "confidence",
    "review_status",
]