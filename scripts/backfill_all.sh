#!/usr/bin/env bash
# Full backfill on every connector that doesn't need a key,
# then the ones that do (if keys are present in .env).
#
# Usage:
#   ./scripts/backfill_all.sh
#
# Expects: a venv already activated or `python` pointing to the right env.

set -u  # -e would abort on first failure; we want to keep going

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

echo ">>> running no-key connectors first"
python -m quantflow_gold.run --all --only-no-key

echo ">>> running key-requiring connectors (will skip if keys missing)"
for src in fred; do
  python -m quantflow_gold.run --source "$src" || true
done

echo ">>> backfill complete"
du -sh data/processed/* 2>/dev/null || true
