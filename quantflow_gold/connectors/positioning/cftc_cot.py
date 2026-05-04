"""CFTC Commitments of Traders — Disaggregated, Futures Only.

Uses the CFTC Socrata public API:
    https://publicreporting.cftc.gov/resource/72hh-3qpy.json

Dataset: Disaggregated Futures Only (Aug 2009+).
Published each Friday 15:30 ET for the Tuesday prior (lag 3 business days).

Trader categories:
  - Producer/Merchant/Processor/User (PMPU) — commercial hedgers
  - Swap Dealers
  - Managed Money  ← the quant favourite (speculators)
  - Other Reportables
  - Non-Reportables (small specs)

Why it matters:
  Managed Money net long extremes = crowded positioning = reversal risk.
  A z-score of managed money net long is a classic signal.

For Legacy format (back to 1986) switch to dataset `6dca-aqww`.
For TFF (financial futures) use `gpe5-46if`.
"""

from __future__ import annotations

import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import http_get


CONTRACTS = {
    "GOLD - COMMODITY EXCHANGE INC.":   "gold",
    "SILVER - COMMODITY EXCHANGE INC.": "silver",
    "COPPER- #1 - COMMODITY EXCHANGE INC.": "copper",  # for cross-asset context
    "PLATINUM - NEW YORK MERCANTILE EXCHANGE": "platinum",
    "PALLADIUM - NEW YORK MERCANTILE EXCHANGE": "palladium",
}


class CftcCotConnector(BaseConnector):
    meta = ConnectorMeta(
        name="cftc_cot",
        category="positioning",
        frequency="weekly",
        requires_key=False,
        description="CFTC Disaggregated COT for COMEX/NYMEX metals",
    )

    BASE = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"

    def fetch(self, start: str = "2015-01-01") -> pd.DataFrame:
        rows = []
        for contract_name, slug in CONTRACTS.items():
            params = {
                "$where": (
                    f"market_and_exchange_names='{contract_name}' "
                    f"AND report_date_as_yyyy_mm_dd >= '{start}T00:00:00.000'"
                ),
                "$limit": 50000,
                "$order": "report_date_as_yyyy_mm_dd ASC",
            }
            try:
                r = http_get(self.BASE, params=params)
                data = r.json()
            except Exception as e:  # noqa: BLE001
                from loguru import logger
                logger.warning(f"[cftc_cot] skip {slug}: {e}")
                continue

            for d in data:
                date = d.get("report_date_as_yyyy_mm_dd")
                # The columns we care about (string → float)
                def f(k):
                    v = d.get(k)
                    try:
                        return float(v) if v is not None else None
                    except (ValueError, TypeError):
                        return None

                metrics = {
                    "open_interest":               f("open_interest_all"),
                    "mm_long":                     f("m_money_positions_long_all"),
                    "mm_short":                    f("m_money_positions_short_all"),
                    "mm_spread":                   f("m_money_positions_spread_all"),
                    "pmpu_long":                   f("prod_merc_positions_long_all"),
                    "pmpu_short":                  f("prod_merc_positions_short_all"),
                    "swap_long":                   f("swap_positions_long_all"),
                    "swap_short":                  f("swap_positions_short_all"),
                    "swap_spread":                 f("swap__positions_spread_all"),
                    "other_long":                  f("other_rept_positions_long_all"),
                    "other_short":                 f("other_rept_positions_short_all"),
                    "other_spread":                f("other_rept_positions_spread"),
                    "nonrept_long":                f("nonrept_positions_long_all"),
                    "nonrept_short":               f("nonrept_positions_short_all"),
                }
                # Derived: net positions
                if metrics["mm_long"] is not None and metrics["mm_short"] is not None:
                    metrics["mm_net"] = metrics["mm_long"] - metrics["mm_short"]
                if metrics["pmpu_long"] is not None and metrics["pmpu_short"] is not None:
                    metrics["pmpu_net"] = metrics["pmpu_long"] - metrics["pmpu_short"]

                for metric_name, value in metrics.items():
                    if value is None:
                        continue
                    rows.append({
                        "date": date,
                        "metric": f"{slug}_{metric_name}",
                        "value": value,
                        "unit": "contracts",
                        "contract": slug,
                    })
        return pd.DataFrame(rows)
