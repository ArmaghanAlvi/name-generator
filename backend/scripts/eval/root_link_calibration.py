"""
Cross-language root-fallback calibration (Breakdown 4, Step 4).

Per EN->target pair:
  POSITIVE -- resolved sense_translations links: cosine(EN sense vector,
              target lexeme's primary embedded visible sense vector).
              Known-good cross-language equivalents.
  RANDOM   -- random embedded EN sense x random embedded target sense.

Reports percentiles, AUC (scale-free), and the floor candidates:
random p95 / p99 per pair, plus random mass admitted at positive p10.
Root selection's fallback floor is chosen from THIS table (Step 5), never
from the within-language table -- different distribution, same anisotropy
lesson as the AUC episode.

USAGE (from backend/): python3 scripts/eval/root_link_calibration.py \
    [--n 2000] [--targets la ru ja ar]
"""
from __future__ import annotations

import argparse
import os
import random
import sys

import numpy as np
from sqlalchemy import func, select, text

sys.path.insert(0, os.getcwd())

from app.db.session import SessionLocal                        # noqa: E402
from app.models.generated_name import Language                 # noqa: E402
from app.models.semantic import (                              # noqa: E402
    Lexeme, Sense, SenseEmbedding, SenseTranslation,
)


def _cos(a, b):
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(np.dot(a, b) / (na * nb)) if na and nb else 0.0


def _auc(pos, neg):
    if not pos or not neg:
        return float("nan")
    allv = np.concatenate([np.asarray(pos), np.asarray(neg)])
    ranks = np.empty(len(allv), dtype=np.float64)
    ranks[allv.argsort()] = np.arange(1, len(allv) + 1)
    np_, nn = len(pos), len(neg)
    return float((ranks[:np_].sum() - np_ * (np_ + 1) / 2) / (np_ * nn))


def _pcts(vals):
    p = np.percentile(vals, [5, 10, 25, 50, 75, 95, 99])
    return "  ".join(f"p{q}:{v:.3f}" for q, v in zip((5, 10, 25, 50, 75, 95, 99), p))


def _rand_embedded(db, language_id, n):
    ids = [sid for (sid,) in db.execute(
        select(SenseEmbedding.sense_id)
        .join(Sense, Sense.id == SenseEmbedding.sense_id)
        .join(Lexeme, Lexeme.id == Sense.lexeme_id)
        .where(Lexeme.language_id == language_id,
               Sense.visibility_status == "visible")
        .order_by(func.random()).limit(n)
    )]
    vecs = dict(db.execute(
        select(SenseEmbedding.sense_id, SenseEmbedding.embedding)
        .where(SenseEmbedding.sense_id.in_(ids))
    ).all())
    return [vecs[i] for i in ids if i in vecs]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--targets", nargs="*", default=["la", "ru", "ja", "ar"])
    args = ap.parse_args()

    with SessionLocal() as db:
        db.execute(text("SET lock_timeout = '30s'"))
        for code in args.targets:
            lang = db.scalars(select(Language).where(Language.code == code)).first()
            if lang is None:
                print(f"===== en->{code}: no language row, skipped")
                continue

            # POSITIVES: sampled resolved links -> (en vector, target vector).
            links = db.execute(
                select(SenseTranslation.sense_id, SenseTranslation.target_lexeme_id)
                .where(SenseTranslation.language_id == lang.id,
                       SenseTranslation.target_lexeme_id.isnot(None))
                .order_by(func.random()).limit(args.n)
            ).all()
            pos: list[float] = []
            for en_sense_id, tgt_lexeme_id in links:
                en_vec = db.scalar(
                    select(SenseEmbedding.embedding)
                    .where(SenseEmbedding.sense_id == en_sense_id)
                )
                tgt_vec = db.scalar(
                    select(SenseEmbedding.embedding)
                    .join(Sense, Sense.id == SenseEmbedding.sense_id)
                    .where(Sense.lexeme_id == tgt_lexeme_id,
                           Sense.visibility_status == "visible")
                    .order_by(Sense.sense_index).limit(1)
                )
                if en_vec is not None and tgt_vec is not None:
                    pos.append(_cos(en_vec, tgt_vec))

            en_lang = db.scalars(select(Language).where(Language.code == "en")).first()
            en_r = _rand_embedded(db, en_lang.id, args.n) # type: ignore
            tg_r = _rand_embedded(db, lang.id, args.n)
            rnd = [_cos(a, b) for a, b in zip(en_r, tg_r)]
            random.shuffle(rnd)

            print(f"===== en->{code}")
            print(f"positive pairs (n={len(pos)}): {_pcts(pos)}")
            print(f"random   pairs (n={len(rnd)}): {_pcts(rnd)}")
            print(f"AUC .............................. {_auc(pos, rnd):.4f}")
            p10 = float(np.percentile(pos, 10))
            adm = 100.0 * float(np.mean(np.asarray(rnd) >= p10))
            print(f"random p95 / p99 (floor cands) ... "
                  f"{float(np.percentile(rnd,95)):.3f} / {float(np.percentile(rnd,99)):.3f}")
            print(f"positive p10 ..................... {p10:.3f} "
                  f"(admits {adm:.1f}% random)")


if __name__ == "__main__":
    main()