import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import contextlib
from app.db.session import SessionLocal
from app.models.semantic import Sense, Lexeme, SenseEmbedding
from app.services.multi_hop_expansion import multi_hop_expand
from app.services.morphology import same_family, longest_common_substring_len
from app.utils.text import normalize_text
from sqlalchemy import select

def root_id(db, word):
    norm = normalize_text(word)
    return db.scalars(
        select(Sense).join(Lexeme, Lexeme.id == Sense.lexeme_id)
        .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
        .where(Lexeme.normalized_lemma == norm, Sense.visibility_status == "visible")
        .order_by((Lexeme.part_of_speech != "noun"), Sense.sense_index)
    ).first().id

for word in ["brave", "storm"]:
    with SessionLocal() as db:
        with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
            nodes = multi_hop_expand(db, root_sense_id=root_id(db, word),
                                     width=3, depth=3, target_language=None)
    # replicate the throttle's family-grouping to show what pairs with what
    expanded = [n for n in nodes if n.depth > 0]
    # already in final order; reconstruct the pre-sort ranking view by anchored
    print(f"=== {word}: family groupings ===")
    kept = []
    for n in expanded:
        lem = normalize_text(n.sense.lexeme.lemma)
        fam_members = [k for k in kept if same_family(lem, k)]
        if fam_members:
            lcs_info = ", ".join(f"{k}(lcs={longest_common_substring_len(lem,k)})"
                                 for k in fam_members)
            print(f"  {lem:16s} throttled x{len(fam_members)} vs: {lcs_info}")
        kept.append(lem)
    print()
