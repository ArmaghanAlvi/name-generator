"""
Per-language cosine-similarity calibration (roadmap Stage 4d).

For each language with embeddings, samples two distributions:
  POSITIVE — resolved same-language synonym edges: cosine(from-sense vector,
             target lexeme's primary embedded sense vector). What "genuinely
             related" looks like in THIS language's region of E5 space.
  RANDOM   — random same-language embedded sense pairs. The noise floor.

Reports percentiles of both and a SUGGESTED root-fallback floor per language
(random p99 — the similarity below which a candidate is indistinguishable
from noise). The final rule is decided at Stage 5c against these numbers;
this script's job is to make that a table read. Cross-language anisotropy is
why these are measured per language and never shared.

USAGE (from backend/):
  python3 scripts/eval/language_similarity_calibration.py [--n 2000] [--languages en la ru ja ar]
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
from sqlalchemy import func, select

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal                        # noqa: E402
from app.models.generated_name import Language                 # noqa: E402
from app.models.semantic import (                              # noqa: E402
    Lexeme, Sense, SenseEmbedding, SenseRelation,
)


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _auc(pos: list[float], neg: list[float]) -> float:
    """P(a random positive scores above a random negative) — Mann-Whitney U,
    normalized. SCALE-FREE: invariant to each language's baseline offset AND
    spread, so it is comparable ACROSS languages in a way (pos p50 - rnd p50)
    is not. 0.5 = no discrimination; 1.0 = perfect. This is the metric the raw
    separation should have been: cosine differences carry each language's cone
    width, which is the very anisotropy the measurement exists to control for.
    """
    if not pos or not neg:
        return float("nan")
    allv = np.concatenate([np.asarray(pos), np.asarray(neg)])
    ranks = np.empty(len(allv), dtype=np.float64)
    ranks[allv.argsort()] = np.arange(1, len(allv) + 1)
    n_pos, n_neg = len(pos), len(neg)
    return float(
        (ranks[:n_pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    )


def _pcts(vals: list[float]) -> str:
    if not vals:
        return "(empty)"
    p = np.percentile(vals, [5, 10, 25, 50, 75, 95, 99])
    return "  ".join(
        f"p{q}:{v:.3f}" for q, v in zip((5, 10, 25, 50, 75, 95, 99), p)
    )


def calibrate(db, lang: Language, n: int, provenances: list[str] | None = None) -> None:
    # --- POSITIVE pairs: resolved synonym edges within this language ---
    # `provenances` splits the positive sample by edge source. An UNSPLIT
    # sample is not comparable across languages: Arabic is the only language
    # whose synonym edges include an AI-TRANSLATED source (awn4, ~24% of its
    # resolved synonym edges), so "known-true synonym" silently means
    # something weaker for ar than for en/la/ru/ja.
    pos_stmt = (
        select(SenseRelation.from_sense_id, SenseRelation.target_lexeme_id)
        .join(Sense, Sense.id == SenseRelation.from_sense_id)
        .join(Lexeme, Lexeme.id == Sense.lexeme_id)
        .where(
            Lexeme.language_id == lang.id,
            SenseRelation.relation_type == "synonym",
            SenseRelation.target_lexeme_id.is_not(None),
        )
    )
    if provenances:
        pos_stmt = pos_stmt.where(SenseRelation.provenance.in_(provenances))
    edge_rows = db.execute(
        pos_stmt.order_by(func.random()).limit(n)
    ).all()

    # target lexeme -> its primary embedded visible sense id
    tgt_lex_ids = list({t for _f, t in edge_rows})
    primary_of: dict[int, int] = {}
    if tgt_lex_ids:
        for lex_id, sense_id in db.execute(
            select(Sense.lexeme_id, Sense.id)
            .join(SenseEmbedding, SenseEmbedding.sense_id == Sense.id)
            .where(
                Sense.lexeme_id.in_(tgt_lex_ids),
                Sense.visibility_status == "visible",
            )
            .order_by(Sense.lexeme_id, Sense.sense_index)
        ).all():
            primary_of.setdefault(lex_id, sense_id)

    pair_ids = [
        (f, primary_of[t]) for f, t in edge_rows
        if t in primary_of and f != primary_of[t]
    ]

    # --- RANDOM pairs: shuffled embedded senses in this language ---
    rand_ids = db.scalars(
        select(SenseEmbedding.sense_id)
        .join(Sense, Sense.id == SenseEmbedding.sense_id)
        .join(Lexeme, Lexeme.id == Sense.lexeme_id)
        .where(Lexeme.language_id == lang.id)
        .order_by(func.random())
        .limit(2 * n)
    ).all()
    rand_pairs = [
        (rand_ids[i], rand_ids[i + 1])
        for i in range(0, len(rand_ids) - 1, 2)
        if rand_ids[i] != rand_ids[i + 1]
    ]

    # --- fetch all needed vectors in one pass ---
    need = {i for p in pair_ids for i in p} | {i for p in rand_pairs for i in p}
    vec: dict[int, np.ndarray] = {}
    need_list = list(need)
    for start in range(0, len(need_list), 5000):
        for sid, v in db.execute(
            select(SenseEmbedding.sense_id, SenseEmbedding.embedding)
            .where(SenseEmbedding.sense_id.in_(need_list[start:start + 5000]))
        ).all():
            vec[sid] = np.asarray(v, dtype=np.float32)

    pos = [_cos(vec[a], vec[b]) for a, b in pair_ids if a in vec and b in vec]
    rnd = [_cos(vec[a], vec[b]) for a, b in rand_pairs if a in vec and b in vec]

    label = lang.code + ( # type: ignore
        f" [{'+'.join(provenances)}]" if provenances else " [all provenances]"
    )
    print(f"\n===== {label}")
    print(f"positive pairs (n={len(pos)}): {_pcts(pos)}")
    print(f"random   pairs (n={len(rnd)}): {_pcts(rnd)}")
    if pos and rnd:
        p10 = float(np.percentile(pos, 10))
        rnd_above_p10 = 100.0 * float(np.mean(np.asarray(rnd) >= p10))
        print(f"AUC (scale-free discrimination) .......... {_auc(pos, rnd):.4f}")
        print(f"proposed floor = positive p10 ............ {p10:.3f}")
        print(f"  random mass admitted at that floor ..... {rnd_above_p10:.1f}%")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--languages", nargs="*", default=["en", "la", "ru", "ja", "ar"])
    ap.add_argument("--provenance", nargs="*", default=None,
                    help="restrict POSITIVE pairs to these edge provenances "
                         "(e.g. --provenance omw-arb)")
    args = ap.parse_args()
    with SessionLocal() as db:
        for code in args.languages:
            lang = db.scalars(select(Language).where(Language.code == code)).first()
            if lang is None:
                print(f"(skipping {code}: no language row)")
                continue
            calibrate(db, lang, args.n, args.provenance)


if __name__ == "__main__":
    main()