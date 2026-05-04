#!/usr/bin/env bash
# Weekly refresh — heavy / slow sources.
# Suggested cron: Saturday 04:00.
#   0 4 * * 6 /path/to/scripts/weekly_refresh.sh >> /tmp/qf_gold_weekly.log 2>&1

set -u

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

WEEKLY=(
  cftc_cot
  sec_edgar
  gdelt
  historical_long
  google_trends
  open_meteo
  central_bank_gold
  perth_mint
)

for src in "${WEEKLY[@]}"; do
  python -m quantflow_gold.run --source "$src" || true
done
