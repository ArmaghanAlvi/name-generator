#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "The working tree has uncommitted changes."
  echo "Commit or stash them before creating a project archive."
  exit 1
fi

OUTPUT="${1:-../name-generator-snapshot.zip}"

git archive \
  --format=zip \
  --output="$OUTPUT" \
  HEAD

echo "Created archive: $OUTPUT"