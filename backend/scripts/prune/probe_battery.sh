#!/usr/bin/env bash
# Stage 6 file-level probe battery driver (B1/B1b/B2/B3/B4/B5).
# Read-only: every probe below streams files and touches no DB.
#
#   ./scripts/prune/probe_battery.sh --check          # verify paths only
#   ./scripts/prune/probe_battery.sh                  # run all
#   ./scripts/prune/probe_battery.sh --only hi,sa,de  # run a subset
set -uo pipefail

KAIKKI="${KAIKKI:-$HOME/Personal-Projects/datasets/kaikki}"
OUT="${OUT:-scripts/prune/probe_out}"

# code:filename  -- EDIT to match your actual downloads (`ls $KAIKKI`).
# ⚠ Naming convention is MIXED in this project: Phase-I baselines show
# kaikki-Latin.jsonl.gz (capitalized) while Stage 5 recorded
# kaikki-greek.jsonl.gz (lowercase). Run --check first, always.
LANGS=(
  "hi:kaikki-Hindi.jsonl.gz"
  "sa:kaikki-Sanskrit.jsonl.gz"
  "de:kaikki-German.jsonl.gz"
  "he:kaikki-Hebrew.jsonl.gz"
  "fa:kaikki-Persian.jsonl.gz"
  "el:kaikki-greek.jsonl.gz"
  "zh:kaikki-Chinese.jsonl.gz"
  "ang:kaikki-OldEnglish.jsonl.gz"
  "non:kaikki-OldNorse.jsonl.gz"
  "es:kaikki-Spanish.jsonl.gz"
  "pl:kaikki-Polish.jsonl.gz"
  "ko:kaikki-Korean.jsonl.gz"
  "cy:kaikki-Welsh.jsonl.gz"
  "ga:kaikki-Irish.jsonl.gz"
  "sw:kaikki-Swahili.jsonl.gz"
  "is:kaikki-icelandic.jsonl.gz"
)

ONLY=""; CHECK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --check) CHECK=1 ;;
    --only)  shift; ONLY=",$1," ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
  shift
done

missing=0
for pair in "${LANGS[@]}"; do
  code="${pair%%:*}"; file="$KAIKKI/${pair#*:}"
  if [ -f "$file" ]; then printf 'ok       %-4s %s\n' "$code" "$file"
  else echo "MISSING  $code  $file"; missing=1; fi
done
[ "$missing" -eq 1 ] && echo "--- fix the paths above before running ---"
[ "$CHECK" -eq 1 ] && exit "$missing"
[ "$missing" -eq 1 ] && exit 1

for pair in "${LANGS[@]}"; do
  code="${pair%%:*}"; file="$KAIKKI/${pair#*:}"
  [ -n "$ONLY" ] && [[ "$ONLY" != *",$code,"* ]] && continue
  d="$OUT/$code"; mkdir -p "$d"
  echo "=== $code   $(date +%H:%M:%S) ==============================="
  ( set -x
    python3 scripts/prune/prune_attribution_probe.py "$file" --examples 20 > "$d/b1_attribution.txt" 2>&1
    python3 scripts/prune/source_structure_scan.py   "$file" --examples 12 > "$d/b2_structure.txt"   2>&1
    python3 scripts/prune/headword_char_census.py    "$file" --lang-code "$code" > "$d/b2_chars.txt" 2>&1
    python3 scripts/prune/arabic_edge_join_probe.py  "$file" --lang-code "$code" --examples 12 > "$d/b3_join.txt" 2>&1
    python3 scripts/prune/name_gloss_probe.py        "$file" --examples 12 > "$d/b5_name_gloss.txt" 2>&1
    python3 scripts/prune/name_homography_probe.py   "$file" --lang-code "$code" --examples 12 > "$d/b5_homography.txt" 2>&1
  ) 2>>"$d/_run.log"
  echo "--- $code headline ---"
  grep -E "^OK:|^!! DRIFT|^  A:|^  B:|^  C:" "$d/b1_attribution.txt" | head -5
  grep -E "rule  7 |rule 12 " "$d/b1_attribution.txt"
  grep -E "UNKNOWN POS" "$d/b1_attribution.txt"
  grep -E "^  P5 canonical" "$d/b3_join.txt"
done
echo "done -> $OUT"