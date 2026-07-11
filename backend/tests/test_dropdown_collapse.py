from app.models.generated_name import Language
from app.models.semantic import Lexeme, Sense, SenseAdminOverride
from app.services.dropdown_ranker import collapse_key, collapse_ranked
from app.services.sense_lookup import SenseCandidate


def make_candidate(
    sense_id,
    glosses,
    *,
    lemma="draw",
    pos="verb",
    lang="en",
    override=None,
    definition="",
):
    return SenseCandidate(
        sense=Sense(id=sense_id, raw_glosses=glosses, definition=definition,
                    sense_index=sense_id, source_order=0),
        lexeme=Lexeme(id=1, lemma=lemma, part_of_speech=pos),
        language=Language(code=lang, name="English"),
        selection_stat=None,
        override=override,
    )


def test_no_duplicates_is_identity():
    ranked = [
        make_candidate(1, ["To pull."]),
        make_candidate(2, ["To drag."]),
    ]
    collapsed = collapse_ranked(ranked)

    assert [c.representative.sense.id for c in collapsed] == [1, 2]
    assert all(c.duplicate_count == 1 for c in collapsed)
    assert all(c.collapsed_sense_ids == () for c in collapsed)


def test_identical_entries_collapse_to_first_ranked():
    ranked = [
        make_candidate(1, ["To pull."]),
        make_candidate(2, ["To pull."]),
        make_candidate(3, ["To pull."]),
    ]
    collapsed = collapse_ranked(ranked)

    assert len(collapsed) == 1
    assert collapsed[0].representative.sense.id == 1
    assert collapsed[0].collapsed_sense_ids == (2, 3)
    assert collapsed[0].duplicate_count == 3


def test_interleaved_duplicates_keep_first_occurrence_position():
    ranked = [
        make_candidate(1, ["To pull."]),
        make_candidate(2, ["To drag."]),
        make_candidate(3, ["To pull."]),
    ]
    collapsed = collapse_ranked(ranked)

    assert [c.representative.sense.id for c in collapsed] == [1, 2]
    assert collapsed[0].collapsed_sense_ids == (3,)


def test_group_path_distinguishes_same_tail():
    a = make_candidate(1, ["Pulling senses:", "The act."])
    b = make_candidate(2, ["Lottery senses:", "The act."])

    assert collapse_key(a) != collapse_key(b)
    assert len(collapse_ranked([a, b])) == 2


def test_pos_is_not_part_of_identity():
    # Decided 2026-07-xx: 93% of true-duplicate groups are cross-POS
    # (colour noun/adj/verb, all identical text) -- POS is excluded from
    # the key so these actually collapse.
    noun = make_candidate(1, ["A metal."], pos="noun")
    verb = make_candidate(2, ["A metal."], pos="verb")
    collapsed = collapse_ranked([noun, verb])

    assert len(collapsed) == 1
    assert collapsed[0].collapsed_sense_ids == (2,)


def test_display_word_is_part_of_identity():
    common = make_candidate(1, ["A male given name."], lemma="gold", pos="name")
    proper = make_candidate(2, ["A male given name."], lemma="Gold", pos="name")

    assert len(collapse_ranked([common, proper])) == 2


def test_admin_override_text_participates_in_key():
    plain = make_candidate(1, ["To pull."])
    overridden = make_candidate(
        2,
        ["Something unrelated."],
        override=SenseAdminOverride(definition_override="To pull."),
    )
    collapsed = collapse_ranked([plain, overridden])

    assert len(collapsed) == 1
    assert collapsed[0].collapsed_sense_ids == (2,)