"""
Morphological-family helpers shared across expansion services.

Extracted from expansion.py so both the single-hop tiered generator and the
multi-hop traversal can throttle same-family words without cross-importing a
private symbol. Behavior is identical to the original expansion.py versions.
"""
from __future__ import annotations


def longest_common_substring_len(a: str, b: str) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def shared_prefix_len(a: str, b: str) -> int:
    n = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        n += 1
    return n


def same_family(a: str, b: str) -> bool:
    """
    True if two lemmas are the same morphological family, judged by SHARED
    PREFIX (stem), not longest common substring.

    English families share a front stem (luminous/luminosity, valorous/valour,
    stormy/stormbound); inflection lives at the back. A prefix test catches
    real families while rejecting two failure modes a substring test falls for:
      - shared SUFFIX collisions: audacious/bodacious (-acious),
        unfearing/daring (-aring) -- different words, same ending.
      - shared INFIX in compounds: superstorm/stormy, superpowered/powerful
        -- the shared root is buried mid-word, not a shared stem.

    Threshold scales with the shorter lemma (60%), floored at 4 chars so short
    coincidental stems (river/rivulet share 'riv') don't group.

    Known limitation (see Stage 3 FAMILY deferral note): members sharing a
    <=5-char root that diverge at char 6 are NOT grouped -- e.g. luminance vs
    luminosity (shared prefix 'lumin' = 5, below threshold). A Snowball stemmer
    was evaluated and rejected: it grouped only an arbitrary partial slice of
    lumin-, broke true families (valorous/valour, tempest/tempest-tossed), and
    added a dependency -- net worse than this rule's single, predictable blind
    spot.
    """
    shorter = min(len(a), len(b))
    if shorter == 0:
        return False
    threshold = max(4, -(-shorter * 6 // 10))  # ceil(0.6 * shorter), floor 4
    return shared_prefix_len(a, b) >= threshold