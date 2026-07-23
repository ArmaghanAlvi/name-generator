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

ENGLISH IS NEVER TOUCHED. English is ~68% of the pool, and every tuned knob
(MIN_EXPANSION_SCORE, ALPHA_ORIGIN, decay, rerank weights) was calibrated
against English's CURRENT candidate pool -- which is itself mildly starved.
Widening it would change rerank inputs and break the byte-identical
invariant. Fixing English is a re-tuning project for the eval harness, not
a bug fix. The guard is a deliberate no-op for 'en'.

SET LOCAL persists to transaction end, so RESET in `finally`. NOT reentrant:
do not nest two scoped_vector_scan blocks on one session -- the inner exit
would clear the outer's setting. Current call sites are sequential, never
nested (the pivot's expand() calls run on ENGLISH senses, which no-op).
"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

MAX_SCAN_TUPLES = 100_000
EF_SEARCH = 100

_VALID_MODES = ("strict_order", "relaxed_order")


@contextmanager
def scoped_vector_scan(
    db: Session, language_code: str | None, *, mode: str = "relaxed_order",
):
    """Enable HNSW iterative scan for non-English filtered vector queries."""
    if (language_code or "en") == "en":
        yield
        return
    if mode not in _VALID_MODES:
        raise ValueError(f"bad iterative_scan mode: {mode!r}")
    db.execute(text(f"SET LOCAL hnsw.iterative_scan = {mode}"))
    db.execute(text(f"SET LOCAL hnsw.max_scan_tuples = {int(MAX_SCAN_TUPLES)}"))
    db.execute(text(f"SET LOCAL hnsw.ef_search = {int(EF_SEARCH)}"))
    try:
        yield
    finally:
        db.execute(text("RESET hnsw.iterative_scan"))
        db.execute(text("RESET hnsw.max_scan_tuples"))
        db.execute(text("RESET hnsw.ef_search"))