"""Perth Mint monthly minted-product sales (gold + silver, troy ounces).

Source: https://www.perthmint.com/news/investor/market-research-and-analysis/

Each month The Perth Mint (Western Australia, official mint of the Australian
government) publishes a sales update at a predictable URL slug:

    /news/investor/market-research-and-analysis/<month>-<year>-sales-update/

The lead sentence has a stable wording, e.g.:

    "The Perth Mint sold 28,244 troy ounces (oz) of gold and 496,707 oz of
     silver in minted product form during May 2025."

Plus a follow-up sentence with PMGOLD (ASX-listed gold-backed ETP) holdings.

Why it matters for gold quants:
- Replaces the dead `us_mint` connector (about.ag mirror frozen 2012).
- Perth Mint is the largest Western government mint by gold production
  (~10% of global newly mined gold, refines for ASX & global wholesalers).
- Monthly minted-product oz = leading indicator of *retail physical demand*
  (vs. ETF inflows = institutional demand). Sharp spikes correlate with
  retail panic / safe-haven flows (e.g. Mar 2020, Mar 2023, Oct 2025).
- PMGOLD AUM trend = listed gold ETF flow proxy for the APAC region.

Coverage observed at build time: October 2024 → present (~16 months and
growing). Older months are not yet on the new URL scheme.

Output metrics (canonical long-format schema):
    perth_mint_gold_oz                  monthly  (troy oz of minted gold sold)
    perth_mint_silver_oz                monthly  (troy oz of minted silver sold)
    perth_mint_silver_gold_ratio_retail monthly  (silver/gold sales ratio)
    pmgold_holdings_oz                  monthly  (ASX:PMGOLD client holdings)
"""

from __future__ import annotations

import re
from datetime import datetime

import pandas as pd
from loguru import logger

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import http_get


_MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]
_MONTH_TO_NUM = {m: i + 1 for i, m in enumerate(_MONTHS)}

_BASE_URL = (
    "https://www.perthmint.com/news/investor/market-research-and-analysis/"
)

_RE_SOLD = re.compile(
    r"sold\s+([\d,]+)\s+(?:troy\s+)?ounces?\s*\(oz\)\s*of\s+gold\s+and\s+"
    r"([\d,]+)\s+oz\s+of\s+silver",
    re.I,
)
_RE_PMGOLD = re.compile(
    r"PMGOLD[^.]*?(\d[\d,]*)\s*ounces", re.I | re.S
)


class PerthMintConnector(BaseConnector):
    meta = ConnectorMeta(
        name="perth_mint",
        category="physical",
        frequency="monthly",
        requires_key=False,
        description="Perth Mint monthly retail gold/silver minted-product sales + PMGOLD ETP holdings",
    )

    def _candidate_months(self) -> list[tuple[int, int, str]]:
        """Enumerate (year, month_num, month_name) candidates from 2024-09 to now."""
        out: list[tuple[int, int, str]] = []
        today = datetime.utcnow()
        for year in range(2024, today.year + 1):
            for i, name in enumerate(_MONTHS):
                month_num = i + 1
                if (year, month_num) > (today.year, today.month):
                    break
                if (year, month_num) < (2024, 10):
                    continue
                out.append((year, month_num, name))
        return out

    def _fetch_one(self, year: int, month_num: int, month_name: str) -> list[dict]:
        url = f"{_BASE_URL}{month_name}-{year}-sales-update/"
        try:
            r = http_get(url, retries=1, timeout=15.0)
        except Exception as exc:
            logger.debug(f"[perth_mint] {month_name}-{year} skipped ({exc.__class__.__name__})")
            return []
        if r.status_code != 200:
            return []

        text = r.text
        m = _RE_SOLD.search(text)
        if not m:
            logger.debug(f"[perth_mint] {month_name}-{year} no sales sentence found")
            return []

        gold_oz = float(m.group(1).replace(",", ""))
        silver_oz = float(m.group(2).replace(",", ""))
        date = pd.Timestamp(year=year, month=month_num, day=1)

        rows: list[dict] = [
            {"date": date, "metric": "perth_mint_gold_oz",
             "value": gold_oz, "unit": "troy_oz"},
            {"date": date, "metric": "perth_mint_silver_oz",
             "value": silver_oz, "unit": "troy_oz"},
        ]
        if gold_oz > 0:
            rows.append({
                "date": date,
                "metric": "perth_mint_silver_gold_ratio_retail",
                "value": silver_oz / gold_oz,
                "unit": "ratio",
            })

        h = _RE_PMGOLD.search(text)
        if h:
            try:
                pmgold = float(h.group(1).replace(",", ""))
                rows.append({
                    "date": date,
                    "metric": "pmgold_holdings_oz",
                    "value": pmgold,
                    "unit": "troy_oz",
                })
            except ValueError:
                pass
        return rows

    def fetch(self) -> pd.DataFrame:
        rows: list[dict] = []
        candidates = self._candidate_months()
        hits = 0
        for year, month_num, month_name in candidates:
            month_rows = self._fetch_one(year, month_num, month_name)
            if month_rows:
                hits += 1
                rows.extend(month_rows)
        logger.info(
            f"[perth_mint] {hits}/{len(candidates)} monthly updates parsed "
            f"({len(rows)} rows)"
        )
        if not rows:
            return pd.DataFrame(columns=["date", "metric", "value", "unit"])
        return pd.DataFrame(rows)
