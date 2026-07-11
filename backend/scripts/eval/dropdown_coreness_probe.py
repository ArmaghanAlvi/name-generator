"""
Offline test: does cosine(sense_embedding, embed_query(lemma)) predict the
central sense?

Caveat baked into the analysis: build_sense_text() prefixes every sense with
"<lemma>: ", so all senses of a word share the lemma token and cosines will be
high and compressed. Spread is reported BEFORE ranking, because a signal with
no dynamic range cannot rank anything no matter what the accuracy says.

Cost if adopted: one embed call per dropdown lookup. Only worth it for a
decisive win.
"""
from __future__ import annotations

import json

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.semantic import SenseEmbedding
from app.services.embedding_provider import embed_query
from app.services.sense_lookup import fetch_sense_candidates
from scripts.eval.dropdown_gold import GOLD, SLATE


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return 0.0 if na == 0 or nb == 0 else float(dot / (na * nb))


def main() -> int:
    report: list[dict] = []

    with SessionLocal() as db:
        for word, _band in SLATE:
            candidates = fetch_sense_candidates(
                db, query=word, language_code="en", limit=500,
            )
            sense_ids = [c.sense.id for c in candidates]

            vectors = {
                row.sense_id: [float(v) for v in row.embedding]
                for row in db.execute(
                    select(SenseEmbedding).where(
                        SenseEmbedding.sense_id.in_(sense_ids)
                    )
                ).scalars()
            }

            query_vector = [float(v) for v in embed_query(word)]
            scored = [
                (sense_id, _cosine(vectors[sense_id], query_vector))
                for sense_id in sense_ids
                if sense_id in vectors
            ]

            if not scored:
                continue

            cosines = [c for _sid, c in scored]
            ranked = sorted(scored, key=lambda pair: -pair[1])
            gold_id = GOLD[word].top1_sense_id
            gold_rank = next(
                (i + 1 for i, (sid, _c) in enumerate(ranked) if sid == gold_id),
                None,
            )

            report.append({
                "word": word,
                "n": len(scored),
                "spread": round(float(max(cosines) - min(cosines)), 4),
                "max_cosine": round(float(max(cosines)), 4),
                "gold_rank_by_cosine": gold_rank,
                "gold_percentile": round(
                    sum(1 for _s, c in scored if c < dict(scored)[gold_id]) /
                    max(1, len(scored) - 1), 3
                ) if gold_id in dict(scored) else None,
                "top1_by_cosine": ranked[0][0],
                "gold_is_top1": bool(ranked[0][0] == gold_id),
            })

    dead = [r["word"] for r in report if r["spread"] < 0.05]
    top1 = sum(r["gold_is_top1"] for r in report) / max(1, len(report))
    mean_spread = sum(r["spread"] for r in report) / max(1, len(report))

    print(json.dumps(report, indent=2))
    print(f"\nmean within-word spread = {mean_spread:.4f}")
    print(f"top1_by_cosine          = {top1:.3f}")
    print(f"words with spread < 0.05 (no discriminative room): {dead or 'none'}")

    with open("scripts/eval/dropdown_coreness.json", "w") as handle:
        json.dump({
            "top1_by_cosine": top1,
            "mean_spread": mean_spread,
            "per_word": report,
        }, handle, indent=2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())