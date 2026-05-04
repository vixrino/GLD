#!/usr/bin/env bash
# Daily refresh — run this via cron/launchd at end-of-day.
#
# Example cron (every weekday 23:10 Europe/Paris):
#   10 23 * * 1-5 /path/to/scripts/daily_refresh.sh >> /tmp/qf_gold.log 2>&1
#
# We keep the heavy long-history connectors on a weekly schedule (see
# weekly_refresh.sh) and only run the daily-moving ones here.

set -u

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

DAILY=(
  yahoo
  fred
  etf_holdings
  sge
  defillama
  stocktwits
  wikipedia
  usgs_earthquakes
  miners_yahoo
)

for src in "${DAILY[@]}"; do
  python -m quantflow_gold.run --source "$src" || true
done
