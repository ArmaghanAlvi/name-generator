import os, contextlib
from backend.app.db.session import SessionLocal
from backend.app.models.semantic import Sense, Lexeme, SenseEmbedding
from backend.app.services.multi_hop_expansion import multi_hop_expand
from backend.app.utils.text import normalize_text
from sqlalchemy import select

WORDS = ["storm", "brave", "light", "river"]
WIDTH, DEPTH = 3, 3

def root_sense_id(db, word):
    norm = normalize_text(word)
    sel = db.scalars(
        select(Sense).join(Lexeme, Lexeme.id == Sense.lexeme_id)
        .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
        .where(Lexeme.normalized_lemma == norm, Sense.visibility_status == "visible")
        .order_by((Lexeme.part_of_speech != "noun"), Sense.sense_index)
    ).first()
    return sel.id if sel else None

with SessionLocal() as db:
    for word in WORDS:
        rid = root_sense_id(db, word)
        if rid is None:
            print(f"=== {word}: no embedded sense ==="); continue
        with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
            nodes = multi_hop_expand(db, root_sense_id=rid, width=WIDTH, depth=DEPTH,
                                     target_language=None)
        print(f"=== {word}: {len(nodes)} nodes (incl. root) ===")
        for n in nodes:
            indent = "  " * n.depth
            print(f"{indent}{n.path[-1]:18s} [{n.score:.3f}] <{n.provenance}> "
                  f"d={n.depth}  via={'>'.join(n.path[:-1]) or '(root)'}")
        print()