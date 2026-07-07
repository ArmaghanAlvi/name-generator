import pytest
from app.services.prune_taxonomy import classify, Tier

# (pos, tags, lemma, definition, expected)
CASES = [
    # --- Tier C: real single-word concepts ---
    ("adj",  [], "prepericardiac", "anterior to the pericardium", Tier.C),
    ("noun", [], "kingwood", "a Brazilian tree with hard violet-brown wood", Tier.C),
    ("verb", [], "canoodle", "to cuddle or caress affectionately", Tier.C),
    # --- Tier A: POS ---
    ("article", [], "the", "used before a noun phrase", Tier.A),
    ("prep", [], "above", "in addition to; besides", Tier.A),
    ("pron", [], "he", "a male person or animal", Tier.A),
    ("intj", [], "eureka", "expressing triumph on a discovery", Tier.A),
    ("suffix", ["morpheme"], "-lysis", "dissolving", Tier.A),
    ("symbol", [], "A", "a tone three fifths above C", Tier.A),
    ("character", [], "P", "the sixteenth letter of the alphabet", Tier.A),
    ("proverb", [], "you can't polish a turd", "something bad can't be improved", Tier.A),
    # --- Tier A: tags ---
    ("noun", ["form-of"], "rockovers", "plural of rockover", Tier.A),
    ("name", ["initialism"], "ODP", "Initialism of Oracle Data Provider", Tier.A),
    ("noun", ["misspelling"], "predeliction", "Misspelling of predilection", Tier.A),
    ("verb", ["pronunciation-spelling"], "fishin'", "Pronunciation spelling of fishing", Tier.A),
    ("noun", ["clipping"], "synbio", "Clipping of synthetic biology", Tier.A),
    ("noun", ["ellipsis"], "registration", "Ellipsis of registration number", Tier.A),
    ("noun", ["vulgar"], "fuckwad", "a large amount", Tier.A),
    ("noun", ["derogatory"], "pissbrain", "a term of abuse", Tier.A),
    ("adj",  ["alt-of"], "gas-lit", "Alternative form of gaslit", Tier.A),
    # --- Tier A: shape ---
    ("noun", [], "s620s", "plural of s620", Tier.A),        # digit
    ("noun", [], "Det.", "abbreviation of detective", Tier.A),  # dotted code
    ("noun", [], "xyzzy", "ab", Tier.A),                   # too-short def
    # --- Tier B: POS ---
    ("name", [], "Shenyang", "a subprovincial city in Liaoning, China", Tier.B),
    ("num",  [], "trillion", "an unspecified very large number", Tier.B),
    # --- Tier B: tags ---
    ("noun", ["archaic"], "mazer", "a large drinking bowl of wood", Tier.B),
    ("noun", ["historical"], "chiflik", "a hereditary landholding in the Ottoman Empire", Tier.B),
    ("noun", ["slang"], "brick", "a kilogram of cocaine", Tier.B),
    ("adj",  ["nonstandard"], "joyness", "the state of joy", Tier.B),
    ("noun", ["plural-only"], "vital statistics", "statistics of births and deaths", Tier.B),
    # --- Tier B: multiword noun/verb ---
    ("noun", [], "soft drink", "a non-alcoholic carbonated drink", Tier.B),
    ("verb", [], "speed up", "to accelerate", Tier.B),
    # --- Tier B: capitalized proper-noun backstop under a common POS ---
    ("noun", [], "Poless", "a Polish woman", Tier.B),
]

@pytest.mark.parametrize("pos,tags,lemma,definition,expected", CASES)
def test_classify(pos, tags, lemma, definition, expected):
    assert classify(pos, tags, lemma, definition) is expected