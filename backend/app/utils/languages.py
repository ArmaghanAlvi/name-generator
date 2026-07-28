"""Language metadata shared by the importer and the pruning taxonomy.

Lives here rather than in kaikki_english.py because prune_taxonomy.py needs
the script lookup for rule 7, and kaikki_english.py already imports
prune_taxonomy — importing back would create a cycle. One dict, one source of
truth: adding language #21 remains a single edit.
"""
from __future__ import annotations

# ISO 639 code -> ISO 15924 script. Drives BOTH:
#   * languages.script, which the frontend reads for RTL rendering
#   * prune_taxonomy rule 7, i.e. whether combining marks are ORTHOGRAPHY in
#     this language or a coding artifact to be dropped
LANGUAGE_SCRIPTS: dict[str, str] = {
    "en": "Latn", "hi": "Deva", "es": "Latn", "ru": "Cyrl", "la": "Latn",
    "el": "Grek", "sa": "Deva", "ang": "Latn", "non": "Latn", "pl": "Latn",
    "ar": "Arab", "he": "Hebr", "fa": "Arab", "ja": "Jpan", "zh": "Hani",
    "ko": "Kore", "cy": "Latn", "ga": "Latn", "de": "Latn", "sw": "Latn",
}