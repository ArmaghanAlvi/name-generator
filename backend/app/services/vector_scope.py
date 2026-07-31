"""
HNSW post-filter starvation guard.

pgvector's HNSW scan returns ~ef_search candidates BEFORE non-vector
predicates apply. A `language_id = X` filter then discards them. Measured
(ef_search=100, LIMIT 15, iterative_scan off):
    la 1/15 - ru 1/15 - ja 5/15 - ar 0/15
ARABIC RETURNED ZERO: its vector rungs (root fallback AND tree traversal)
have been dead since the day Arabic was embedded.

ef_search CANNOT fix this -- REFUTED BY MEASUREMENT. It caps at 1000, and
at 800 Latin still returned only 6 of 15. (An `<->` control run returned
15/15 at every ef value because no L2 index exists, so it fell back to an
exact seq scan at 2.8-4.1s: that is the correctness oracle -- 15 real
Latin neighbors DO exist -- and also why exact scan is not the answer.)

FIX: hnsw.iterative_scan (pgvector >= 0.8; this DB runs 0.8.3), which keeps
pulling candidates until the post-filter yields enough. Both modes give
15/15 for all four languages.

  MODE           LIMIT 15                    LIMIT 1
  strict_order   la 642 ru 134 ja 21 ar 342  la 126 ru 7 ja 3 ar 189  (ms)
  relaxed_order  la  70 ru  48 ja 12 ar  59  la   2 ru 1 ja 1 ar  10

  strict_order   exact distance ordering. Used by ROOT SELECTION: it takes
                 LIMIT 1 with no downstream rerank, so "nearest" must mean
                 nearest -- and at LIMIT 1 it is cheap (<=189ms worst case,
                 and only on the fallback rung, which fires last).
  relaxed_order  may return slightly out of distance order. Used by TREE
                 TRAVERSAL, whose candidates are reranked downstream anyway
                 and which runs per-node, so cost dominates.

max_scan_tuples MUST be raised with it: the default is 20,000, but the
measurements above used 100,000 and Latin's visible pool alone is ~56K.

ENGLISH WAS EXEMPT UNTIL 2026-07-31. The original exemption assumed English's
starvation was mild (~40 tuples) and that widening it was a re-tuning project
rather than a correctness fix. Measured at 6-language scale (post-ga import):
severe, non-mild starvation -- 0 of 500 rows on 5 of 9 nodes in a width-3/
depth-3 traversal, silently dropping real neighbors like "radiance" (0.907
cosine to "light"). English is no longer exempt (see scoped_vector_scan's
depth guard, which also restores reentrancy safety the old no-op provided
for free).

MAX_SCAN_TUPLES stayed at the pre-existing 100,000 for non-English, but a
sweep (light/whisper, width=3 depth=3) showed full target-word recall down
to 5,000 with no clear latency relationship across 5K-100K -- concurrency
testing confirmed the English throughput cost (~4x on en-only requests, per
http_concurrency.py) comes from enabling iterative scan at all, not from the
ceiling's size. Kept at 20,000 as a safety margin above the measured floor,
not because a higher value measurably helps.

SET LOCAL persists to transaction end, so RESET in `finally`. NOT reentrant:
do not nest two scoped_vector_scan blocks on one session -- the inner exit
would clear the outer's setting. Current call sites are sequential, never
nested (the pivot's expand() calls run on ENGLISH senses, which no-op).
"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

MAX_SCAN_TUPLES = 20_000
EF_SEARCH = 100

_VALID_MODES = ("strict_order", "relaxed_order")


@contextmanager
def scoped_vector_scan(
    db: Session, language_code: str | None, *, mode: str = "relaxed_order",
):
    """Enable HNSW iterative scan for filtered vector queries.

    ENGLISH IS NO LONGER EXEMPT (revised 2026-07-31). The original exemption
    assumed English's starvation was mild (~40 tuples) and that widening it
    was a re-tuning project rather than a correctness fix. Measured at
    6-language scale: English returned ZERO rows on 5 of 9 nodes in a
    width-3/depth-3 `light` traversal while the exact-scan oracle returned
    500 (top candidate `radiance` at 0.907). The starvation is no longer
    mild, and its output is a function of the GLOBAL index composition --
    so English results silently shift with every language imported.

    REENTRANCY: the English no-op used to be what made nesting safe (the
    pivot's expand() runs on English senses inside a non-English scan). With
    English no longer a no-op, an inner exit would RESET the outer language's
    settings mid-traversal. The depth guard below makes the OUTERMOST block
    own the settings; inner blocks inherit them and touch nothing.
    """
    if mode not in _VALID_MODES:
        raise ValueError(f"bad iterative_scan mode: {mode!r}")

    depth = getattr(db, "_vector_scan_depth", 0)
    if depth:
        # Already inside a scan on this session: inherit, do not re-SET and
        # do not RESET on exit (that would clear the outer block's settings).
        yield
        return

    db._vector_scan_depth = 1  # type: ignore[attr-defined]
    db.execute(text(f"SET LOCAL hnsw.iterative_scan = {mode}"))
    db.execute(text(f"SET LOCAL hnsw.max_scan_tuples = {int(MAX_SCAN_TUPLES)}"))
    db.execute(text(f"SET LOCAL hnsw.ef_search = {int(EF_SEARCH)}"))
    try:
        yield
    finally:
        db._vector_scan_depth = 0  # type: ignore[attr-defined]
        db.execute(text("RESET hnsw.iterative_scan"))
        db.execute(text("RESET hnsw.max_scan_tuples"))
        db.execute(text("RESET hnsw.ef_search"))