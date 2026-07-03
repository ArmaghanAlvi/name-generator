"""
Divergence map: capture what /explore-v2 currently returns across the
probe set at every breadth x depth cell, mapping UI breadth/depth onto the
CURRENT request contract (the same mapping explore.ts uses today). Diffed
against engine_reference.json to locate the divergence.
"""
import os
import sys
import json
import contextlib

sys.path.insert(0, os.getcwd())

from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.semantic import Sense, Lexeme, SenseEmbedding
from app.schemas.explore_v2 import ExploreV2Request
from app.api.routes.explore_v2 import explore_v2
from app.utils.text import normalize_text

from scripts.eval.capture_engine_reference import most_used_sense_id

PROBE_WORDS = [
    "brave", "light", "storm", "river", "calm",
    "joy", "shadow", "fierce", "gold", "whisper",
]
GRID = [(b, d) for b in (0, 1, 2, 3) for d in (0, 1, 2, 3)]


def root_id(db, word):
    norm = normalize_text(word)
    r = db.scalars(
        select(Sense).join(Lexeme, Lexeme.id == Sense.lexeme_id)
        .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
        .where(Lexeme.normalized_lemma == norm, Sense.visibility_status == "visible")
        .order_by((Lexeme.part_of_speech != "noun"), Sense.sense_index)
    ).first()
    return r.id if r else None


def current_mapping(breadth, depth):
    # EXACT replica of explore.ts exploreSelectedSenses mapping TODAY.
    exact_only = breadth == 0 or depth == 0
    return {
        "expansionCount": 0 if exact_only else breadth,
        "width": None if (exact_only or depth == 1) else breadth,
        "depth": 1 if exact_only else depth,
    }


def capture_cell(db, sid, breadth, depth):
    m = current_mapping(breadth, depth)
    req = ExploreV2Request(
        selectedSenseIds=[sid],
        queryText="",
        expansionCount=m["expansionCount"],
        width=m["width"],
        depth=m["depth"],
        language=None,
        minLength=0,
        maxLength=30,
    )
    with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
        resp = explore_v2(req, db=db)
    return [
        {
            "word": r.name,
            "sense_id": r.matchedSenseId,
            "depth": r.depth,
            "provenance": r.provenance,
            "weight": round(r.relationshipWeight, 4),
        }
        for r in resp.results
    ]


def main():
    out = {}
    with SessionLocal() as db:
        for word in PROBE_WORDS:
            sid = most_used_sense_id(db, word)
            if sid is None:
                out[word] = {"skipped": "no embedded visible sense"}
                continue
            out[word] = {"root_sense_id": sid, "cells": {}}
            for breadth, depth in GRID:
                key = f"b{breadth}_d{depth}"
                out[word]["cells"][key] = capture_cell(db, sid, breadth, depth)

    path = "scripts/eval/api_current.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()