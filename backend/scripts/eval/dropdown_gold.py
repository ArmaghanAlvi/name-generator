"""
Gold labels for dropdown rank quality.

Zero-review note: these are hand-assigned EVAL labels, the same category as
the shape tags in scripts/eval/corpus.py. They are never read by the import
pipeline, the ranker, or any production code path — only by
scripts/eval/dropdown_rank_probe.py. The zero-review constraint governs
pipeline data, not evaluation ground truth.

Labeling question (the objective, per the roadmap): everyday-centrality.
    "If someone said this word aloud with no context, which listed meaning
     would a fluent speaker assume?"
NOT "which meaning makes the best name." A user who searches 'fire' wanting
passion and a user who wants combustion should both be served by surfacing
the central sense first.
"""
from __future__ import annotations

from dataclasses import dataclass


# (word, band). Bands: S=2-5 senses, M=6-20, L=21-60, XL=60+.
SLATE: list[tuple[str, str]] = [
    ("sneaky",   "S"),
    ("vast",     "S"),
    ("joy",      "S"),
    ("strength", "S"),
    ("hope",     "M"),
    ("grace",    "M"),
    ("gold",     "M"),
    ("star",     "M"),
    ("storm",    "L"),
    ("bright",   "L"),
    ("fire",     "L"),
    ("light",    "L"),
    ("head",     "XL"),
    ("draw",     "XL"),
]


@dataclass(frozen=True)
class GoldLabel:
    word: str

    # The sense that should rank first.
    top1_sense_id: int

    # Durable identity check. source_locator hashes (entry, pos, etymology,
    # sense_index, gloss) and none of those change under this roadmap, so it
    # survives a re-import. The probe asserts sense_id and locator still agree
    # and fails loudly if the DB was rebuilt underneath the labels.
    top1_source_locator: str

    # First ~60 chars of displayDefinition, so the file is human-readable and
    # a stale label is obvious on sight.
    top1_snippet: str

    # Senses that would be defensible in the top slot. top1 is always a member.
    acceptable_sense_ids: frozenset[int] = frozenset()

    # True when two senses are genuinely tied for centrality (e.g. a noun and
    # its adjective). The probe reports metrics with and without these.
    ambiguous: bool = False


GOLD: dict[str, GoldLabel] = {
    "sneaky": GoldLabel(
        word="sneaky", 
        top1_sense_id=233161,
        top1_source_locator="kaikki:en:sneaky:adj::1:0ece275bb0d52450",
        top1_snippet="Elusive; difficult to capture or observe due to "
                    "constantly outwitting the adversaries.",
        acceptable_sense_ids=frozenset({233161}),
    ),
    "vast": GoldLabel(
        word="vast",
        top1_sense_id=77020,
        top1_source_locator="kaikki:en:vast:adj::1:62b4dc1227f6175e",
        top1_snippet="Very large or wide (literally or figuratively).",
        acceptable_sense_ids=frozenset({77020, 77021}),
        ambiguous=True,
        # note: 77020/77021 are near-synonymous "very large" adjective senses;
        # a fluent speaker wouldn't distinguish them without more context.
    ),
    "joy": GoldLabel(
        word="joy",
        top1_sense_id=57055,
        top1_source_locator="kaikki:en:joy:noun::1:29f95f46b71b1e42",
        top1_snippet="A feeling of extreme happiness or cheerfulness, especially "
                      "related to the acquisition or expectation of something.",
        acceptable_sense_ids=frozenset({57055}),
    ),
    "strength": GoldLabel(
        word="strength", 
        top1_sense_id=99154,
        top1_source_locator="kaikki:en:strength:noun::2:ce30875caceadf55",
        top1_snippet="The intensity of a force or power; potency.",
        acceptable_sense_ids=frozenset({99154, 99153}),
    ),
    "hope": GoldLabel(
        word="hope",
        top1_sense_id=83512,
        top1_source_locator="kaikki:en:hope:noun:2:1:640e8d7c4cbcc235",
        top1_snippet="The feeling of trust, confidence, belief or expectation "
                      "that something wished for can or will happen.",
        acceptable_sense_ids=frozenset({83512, 83507}),
        ambiguous=True,
        # note: noun ("the feeling") vs. verb ("to want something to happen")
        # are both fully central; picked the noun as top1.
    ),
    "grace": GoldLabel(
        word="grace", 
        top1_sense_id=71785,
        top1_source_locator="kaikki:en:grace:noun::5:ef68bd1a67f8de69",
        top1_snippet="Elegant movement; elegance of movement; balance or poise.",
        acceptable_sense_ids=frozenset({71785, 71781}),
        # note: secular "charm" (71781) vs. elegance-of-movement (71785) vs.
        # favor/divine grace (71787) — picked elegance as most universal.
    ),
    "gold": GoldLabel(
        word="gold",
        top1_sense_id=8825,
        top1_source_locator="kaikki:en:gold:noun:1:1:76954a96da328b17",
        top1_snippet="A heavy yellow elemental metal of great value, with "
                      "atomic number 79 and symbol Au.",
        acceptable_sense_ids=frozenset({8825}),
    ),
    "star": GoldLabel(
        word="star",
        top1_sense_id=2860,
        top1_source_locator="kaikki:en:star:noun::1:981a6278ab71a252",
        top1_snippet="Any small, natural and bright dot in the sky, most "
                      "visible in the night or twilight sky.",
        acceptable_sense_ids=frozenset({2860}),
        # note: 2861 ("a planet thought to influence one's fate") yields a
        # larger expansion, but is an explicitly derived sub-sense of 2860.
        # Yield is tested as a Stage 3 signal against these labels, not baked
        # into them.
    ),
    "storm": GoldLabel(
        word="storm",
        top1_sense_id=7459,
        top1_source_locator="kaikki:en:storm:noun:1:1:7236ec89f62b725a",
        top1_snippet="Any disturbed state of the atmosphere causing "
                      "destructive or unpleasant weather.",
        acceptable_sense_ids=frozenset({7459}),
    ),
    "bright": GoldLabel(
        word="bright",
        top1_sense_id=24898,
        top1_source_locator="kaikki:en:bright:adj:1:1:792e93c0b8ab2d53",
        top1_snippet="Emitting much light; visually dazzling; luminous, "
                      "lucent, radiant.",
        acceptable_sense_ids=frozenset({24898}),
    ),
    "fire": GoldLabel(
        word="fire", 
        top1_sense_id=22074,
        top1_source_locator="kaikki:en:fire:noun:1:4:4ea2b92939d4bea3",
        top1_snippet="The aforementioned chemical reaction of burning, "
                    "considered one of the Classical elements or basic "
                    "elements of matter.",
        acceptable_sense_ids=frozenset({22074, 22071, 22072, 22073}),
        ambiguous=True,
        # note: the abstract reaction (22071), an intentionally-created
        # instance (22072), and an accidental occurrence (22073) are all
        # near-equally central
    ),
    "light": GoldLabel(
        word="light", 
        top1_sense_id=23466,
        top1_source_locator="kaikki:en:light:noun:1:4:9b6dca72d1a98a53",
        top1_snippet="A source of illumination.",
        acceptable_sense_ids=frozenset({23466, 23463}),
        ambiguous=True,
    ),
    "head": GoldLabel(
        word="head",
        top1_sense_id=665,
        top1_source_locator="kaikki:en:head:noun:1:1:cdbb01b3a6ef5d7f",
        top1_snippet="The part of the body of an animal or human which "
                      "contains the brain, mouth, and main sense organs.",
        acceptable_sense_ids=frozenset({665, 667}),
    ),
    "draw": GoldLabel(
        word="draw",
        top1_sense_id=17799,
        top1_source_locator="kaikki:en:draw:verb::129:fd663845f4c4780b",
        top1_snippet="To produce (a figure, line, picture, representation of "
                      "something, etc.) with a piece of chalk, a crayon, a pen.",
        acceptable_sense_ids=frozenset({17799, 17671, 17814}),
        ambiguous=True,
        # note: draw has at least 3 unrelated central meanings — to pull
        # (17671), to sketch (17799), a tied game (17814). Picked "to
        # sketch" as top1 on the theory it's the most common standalone
        # usage, but this is the least confident pick on the slate.
    ),
}