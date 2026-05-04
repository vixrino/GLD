"""US Treasury fiscal data — TGA balance + total public debt (no API key).

Endpoint:  https://api.fiscaldata.treasury.gov/services/api/fiscal_service/...
Docs:      https://fiscaldata.treasury.gov/api-documentation/
Auth:      none. Generous rate limits (1k req/h soft cap).

Why this matters for gold:
- The Treasury General Account (TGA) at the Fed acts as a system-liquidity
  drain when it is built up and a system-liquidity injection when it is
  spent down. TGA dynamics are now widely watched as a real-time net
  liquidity proxy alongside Fed RRP (which is in `fred`).
- Total public debt outstanding is the long-run "currency debasement"
  story. A simple z-score of (debt growth rate) is a known input for
  gold-price regression studies.

Series captured (one row per record_date, several metrics each):
- tga_open_balance         (Operating Cash Balance, Treasury General Account, USD millions)
- tga_total_deposits       (Total TGA deposits, USD millions)
- tga_total_withdrawals    (Total TGA withdrawals, USD millions)
- debt_held_by_public      (USD)
- debt_intragov_holdings   (USD)
- debt_total_public_debt   (USD)
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import http_get


BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"

# (endpoint, friendly slug, list of (account_type|None, field, metric, unit))
TGA_ACCOUNTS: dict[str, tuple[str, str]] = {
    "Treasury General Account (TGA) Opening Balance": ("tga_open_balance", "mln_usd"),
    "Total TGA Deposits (Table II)":                  ("tga_total_deposits", "mln_usd"),
    "Total TGA Withdrawals (Table II) (-)":           ("tga_total_withdrawals", "mln_usd"),
}

DEBT_FIELDS: list[tuple[str, str, str]] = [
    ("debt_held_public_amt",  "debt_held_by_public",      "usd"),
    ("intragov_hold_amt",     "debt_intragov_holdings",   "usd"),
    ("tot_pub_debt_out_amt",  "debt_total_public",        "usd"),
]


class TreasuryTgaConnector(BaseConnector):
    meta = ConnectorMeta(
        name="treasury_tga",
        category="macro",
        frequency="daily",
        requires_key=False,
        description="US Treasury TGA cash balance + total public debt (fiscaldata API)",
    )

    def _paginate(self, endpoint: str, params: dict) -> Iterable[dict]:
        """Yield rows from a paginated fiscaldata endpoint."""
        from loguru import logger
        page = 1
        size = 5000
        while True:
            try:
                r = http_get(
                    f"{BASE}{endpoint}",
                    params={**params, "page[number]": page, "page[size]": size},
                    timeout=30.0,
                    retries=2,
                )
                payload = r.json()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[treasury_tga] {endpoint} page {page} failed: {e}")
                return
            data = payload.get("data", [])
            if not data:
                return
            for row in data:
                yield row
            if len(data) < size:
                return
            page += 1

    def fetch(self, start: str = "2010-01-01") -> pd.DataFrame:
        rows: list[dict] = []

        # 1) TGA daily operating cash balance (DTS)
        for raw in self._paginate(
            "/v1/accounting/dts/operating_cash_balance",
            {"filter": f"record_date:gte:{start}", "sort": "record_date"},
        ):
            account = raw.get("account_type")
            if account not in TGA_ACCOUNTS:
                continue
            slug, unit = TGA_ACCOUNTS[account]
            for col in ("open_today_bal", "close_today_bal"):
                v = raw.get(col)
                if v in (None, "null", ""):
                    continue
                try:
                    val = float(v)
                except (TypeError, ValueError):
                    continue
                suffix = "_open" if col == "open_today_bal" else "_close"
                rows.append({
                    "date": raw["record_date"],
                    "metric": f"{slug}{suffix}",
                    "value": val,
                    "unit": unit,
                })

        # 2) Total public debt (debt to penny, daily)
        for raw in self._paginate(
            "/v2/accounting/od/debt_to_penny",
            {"filter": f"record_date:gte:{start}", "sort": "record_date"},
        ):
            for col, metric, unit in DEBT_FIELDS:
                v = raw.get(col)
                if v in (None, "null", ""):
                    continue
                try:
                    val = float(v)
                except (TypeError, ValueError):
                    continue
                rows.append({
                    "date": raw["record_date"],
                    "metric": metric,
                    "value": val,
                    "unit": unit,
                })

        return pd.DataFrame(rows)
