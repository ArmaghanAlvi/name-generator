from app.extractors.oewn_xml import (
    candidate_slug_from_synset_id,
    concept_label_from_synonyms,
)


def test_candidate_slug_from_oewn_synset_id_does_not_double_prefix() -> None:
    assert (
        candidate_slug_from_synset_id("oewn-01136251-v")
        == "oewn_01136251_v"
    )


def test_candidate_slug_from_ewn_synset_id_adds_oewn_prefix() -> None:
    assert (
        candidate_slug_from_synset_id("ewn-01136251-v")
        == "oewn_01136251_v"
    )


def test_concept_label_from_synonyms_uses_readable_words() -> None:
    assert (
        concept_label_from_synonyms(
            ["burn", "combust", "go_up"],
            fallback_slug="oewn_01136251_v",
        )
        == "Burn / Combust / Go Up"
    )