import orjson
from pathlib import Path
from collections import Counter
from app.services.prune_taxonomy import classify, Tier, sole_alt_trigger

path = Path("/tmp/kaikki_slice.jsonl")
tiers: Counter = Counter()
provisional = 0
total = 0

with open(path, "rb") as f:
    for line in f:
        entry = orjson.loads(line)
        word = str(entry.get("word") or "").strip()
        pos = str(entry.get("pos") or "").strip()
        if not word or not pos:
            continue
        for sense_data in entry.get("senses") or []:
            raw_glosses = [
                str(g) for g in (sense_data.get("glosses") or sense_data.get("raw_glosses") or [])
            ]
            definition = raw_glosses[0].strip() if raw_glosses else ""
            tags = [str(t) for t in sense_data.get("tags", [])]
            tier = classify(pos, tags, word, definition)
            tiers[tier] += 1
            total += 1
            if tier is Tier.A and sole_alt_trigger(pos, tags, word, definition):
                provisional += 1

print(f"total senses: {total}")
for t in Tier:
    n = tiers[t]
    print(f"{t.value}: {n} ({100*n/total:.1f}%)")
print(f"provisional (subset of A): {provisional} ({100*provisional/total:.1f}%)")