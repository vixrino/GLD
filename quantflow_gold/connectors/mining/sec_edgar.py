"""SEC EDGAR — 10-K / 10-Q / 8-K filings for major gold miners.

EDGAR data API (no key, just a User-Agent with a real email):
    https://data.sec.gov/submissions/CIK{cik}.json

We don't parse the full 10-K here (too heavy / company-specific). Instead we
output the *filing events* (date of each 10-K, 10-Q, 8-K) which are already
powerful signals:
  - filing date = information release = typical vol / drift event
  - number of 8-Ks / quarter = "corporate action pressure"
  - gap between period-end and filing = "late filing" risk

Additionally we pull `companyfacts` for standard US-GAAP tags that matter for
miners, when exposed:
  - Revenues
  - CostOfGoodsAndServicesSold
  - GoldProducedOrSoldInTroyOunces  (non-GAAP; rare)
  - ProvedAndProbableMineralReserves (extension taxonomy)
  - AverageRealizedPrice  (rare)

Covered miners (CIK mapping verified 2025; can be extended):
  NEM  — Newmont               0001164727
  GOLD — Barrick Gold          0000756894
  AEM  — Agnico Eagle Mines    0000002809
  KGC  — Kinross Gold          0000701818
  FNV  — Franco-Nevada         0001492869
  WPM  — Wheaton Precious M.   0001323404
  GFI  — Gold Fields           0001172724
  AU   — AngloGold Ashanti     0001067993
  HL   — Hecla Mining          0000719413
  PAAS — Pan American Silver   0000822993
  AG   — First Majestic        0001308648
"""

from __future__ import annotations

import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import env, http_get


MINERS = {
    "NEM":  ("0001164727", "newmont"),
    "GOLD": ("0000756894", "barrick"),
    "AEM":  ("0000002809", "agnico_eagle"),
    "KGC":  ("0000701818", "kinross"),
    "FNV":  ("0001492869", "franco_nevada"),
    "WPM":  ("0001323404", "wheaton_precious"),
    "GFI":  ("0001172724", "gold_fields"),
    "AU":   ("0001067993", "anglogold"),
    "HL":   ("0000719413", "hecla"),
    "PAAS": ("0000822993", "pan_american"),
    "AG":   ("0001308648", "first_majestic"),
}

FACT_TAGS_OF_INTEREST = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "CostOfGoodsAndServicesSold",
    "GrossProfit",
    "NetIncomeLoss",
    "CashAndCashEquivalentsAtCarryingValue",
    "LongTermDebtNoncurrent",
    "Assets",
    "Liabilities",
    "StockholdersEquity",
]


class SecEdgarConnector(BaseConnector):
    meta = ConnectorMeta(
        name="sec_edgar",
        category="mining",
        frequency="event",
        requires_key=False,
        description="SEC EDGAR filings (dates) + selected US-GAAP facts for major gold miners",
    )

    SUBS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
    FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

    def _ua(self) -> dict:
        return {"User-Agent": env("SEC_USER_AGENT", default="QuantFlow Gold ops@example.com")}

    def _fetch_submissions(self, cik: str) -> dict:
        r = http_get(self.SUBS_URL.format(cik=cik), headers=self._ua())
        return r.json()

    def _fetch_facts(self, cik: str) -> dict:
        r = http_get(self.FACTS_URL.format(cik=cik), headers=self._ua())
        return r.json()

    def fetch(self) -> pd.DataFrame:
        from loguru import logger
        rows: list[dict] = []

        for ticker, (cik, slug) in MINERS.items():
            # --- filings timeline ---
            try:
                sub = self._fetch_submissions(cik)
                rec = sub.get("filings", {}).get("recent", {})
                forms = rec.get("form", [])
                dates = rec.get("filingDate", [])
                accessions = rec.get("accessionNumber", [])
                periods = rec.get("reportDate", [])
                for form, dt, acc, per in zip(forms, dates, accessions, periods):
                    if form not in {"10-K", "10-Q", "8-K", "20-F", "40-F", "6-K"}:
                        continue
                    try:
                        filing_date = pd.Timestamp(dt)
                    except Exception:
                        continue
                    rows.append({
                        "date": filing_date,
                        "metric": f"edgar_{slug}_filing_{form.replace('-', '').lower()}",
                        "value": 1.0,
                        "unit": "event",
                        "ticker": ticker,
                        "accession": acc,
                        "reporting_period": per,
                    })
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[sec_edgar] submissions {ticker}: {e}")

            # --- standardized facts ---
            try:
                facts = self._fetch_facts(cik).get("facts", {}).get("us-gaap", {})
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[sec_edgar] facts {ticker}: {e}")
                continue

            for tag in FACT_TAGS_OF_INTEREST:
                tag_data = facts.get(tag)
                if not tag_data:
                    continue
                units = tag_data.get("units", {})
                for unit, vals in units.items():
                    for v in vals:
                        end = v.get("end")
                        val = v.get("val")
                        if end is None or val is None:
                            continue
                        try:
                            dt = pd.Timestamp(end)
                            val_f = float(val)
                        except Exception:
                            continue
                        rows.append({
                            "date": dt,
                            "metric": f"edgar_{slug}_{tag.lower()}",
                            "value": val_f,
                            "unit": unit,
                            "ticker": ticker,
                            "fiscal_period": v.get("fp"),
                            "fy": v.get("fy"),
                            "form": v.get("form"),
                        })

        return pd.DataFrame(rows)
