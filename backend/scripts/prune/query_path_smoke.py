"""3c smoke test: run a real multi-hop expansion so the changed query paths
(expansion.selected_lemmas / _apply_family_diversity_penalty,
multi_hop_expansion._apply_cross_hop_family_throttle) actually execute.
Read-only. Prints a stable digest for before/after comparison."""
import os
import sys

from sqlalchemy import select

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal  # noqa: E402
from app.models.semantic import Lexeme, Sense, SenseEmbedding
from app.services.multi_hop_expansion import multi_hop_expand

QUERY_LEMMA = "river"   # any lemma you've used before is fine

with SessionLocal() as db:
    sense = db.scalars(
        select(Sense)
        .join(Lexeme, Lexeme.id == Sense.lexeme_id)
        .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
        .where(
            Lexeme.normalized_lemma == QUERY_LEMMA,
            Sense.visibility_status == "visible",
        )
        .order_by(Sense.sense_index)
        .limit(1)
    ).first()
    if sense is None:
        raise SystemExit(f"no embedded visible sense for {QUERY_LEMMA!r}")

    nodes = multi_hop_expand(db, root_sense_id=sense.id, width=3, depth=2)
    for n in nodes:
        print(f"{n.depth}  {n.sense.lexeme.lemma:<24} "
              f"{n.anchored_score:.4f}  {n.provenance}")