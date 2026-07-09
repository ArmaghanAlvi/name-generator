from app.models.semantic import Sense, SenseAdminOverride
from app.services.sense_display import sense_display_for


def make_sense(raw_glosses, definition=""):
    return Sense(raw_glosses=raw_glosses, definition=definition)


def test_single_gloss_is_used_verbatim():
    # 548,013 of 560,853 visible senses take this path — must be a no-op.
    sense = make_sense(
        ["The stall from which a horse begins the race."],
        definition="The stall from which a horse begins the race.",
    )
    display = sense_display_for(sense)

    assert display.definition == "The stall from which a horse begins the race."
    assert display.group_path == ()
    assert display.group_label is None


def test_header_plus_specific_gloss_splits():
    # draw, sense 17671
    sense = make_sense(
        [
            "Senses relating to exerting force or pulling.",
            "To pull (someone or something) in a particular direction.",
        ],
        definition="Senses relating to exerting force or pulling.",
    )
    display = sense_display_for(sense)

    assert display.definition == (
        "To pull (someone or something) in a particular direction."
    )
    assert display.group_path == (
        "Senses relating to exerting force or pulling.",
    )
    assert display.group_label == "Senses relating to exerting force or pulling."


def test_redundant_header_is_dropped():
    # draw, sense 17811 — definition already restates the header.
    sense = make_sense(
        [
            "The act of drawing:",
            "The act of drawing a gun from a holster, etc.",
        ],
    )
    display = sense_display_for(sense)

    assert display.definition == "The act of drawing a gun from a holster, etc."
    assert display.group_path == ()


def test_same_header_kept_when_definition_diverges():
    # draw, sense 17812 — same header, non-redundant here.
    sense = make_sense(
        [
            "The act of drawing:",
            "The procedure by which the result of a lottery is determined.",
        ],
    )
    display = sense_display_for(sense)

    assert display.group_path == ("The act of drawing:",)


def test_short_header_is_never_treated_as_redundant():
    sense = make_sense(["Of:", "Of a person, strong."])
    display = sense_display_for(sense)

    assert display.group_path == ("Of:",)


def test_three_glosses_produce_two_group_segments():
    sense = make_sense(["Outer.", "Middle.", "The actual meaning."])
    display = sense_display_for(sense)

    assert display.definition == "The actual meaning."
    assert display.group_path == ("Outer.", "Middle.")
    assert display.group_label == "Outer. > Middle."


def test_blank_and_non_string_glosses_are_filtered():
    sense = make_sense(["  ", None, "Header.", "", "Meaning."], definition="x")
    display = sense_display_for(sense)

    assert display.definition == "Meaning."
    assert display.group_path == ("Header.",)


def test_empty_glosses_fall_back_to_stored_definition():
    sense = make_sense([], definition="A stored definition.")
    display = sense_display_for(sense)

    assert display.definition == "A stored definition."
    assert display.group_path == ()


def test_admin_override_wins_and_drops_group():
    sense = make_sense(["Header.", "Meaning."])
    override = SenseAdminOverride(definition_override="Curated text.")

    display = sense_display_for(sense, override)

    assert display.definition == "Curated text."
    assert display.group_path == ()


def test_override_without_definition_override_is_ignored():
    sense = make_sense(["Header.", "Meaning."])
    override = SenseAdminOverride(is_hidden=True, definition_override=None)

    display = sense_display_for(sense, override)

    assert display.definition == "Meaning."