"""Shanghai Gold Exchange — daily reports (English portal).

Endpoint (no auth, but data only available since 2024-01-01 via this URL):
    https://en.sge.com.cn/data/data_daily_international_new?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD

Contracts of interest (the ones quants care about for China demand):
    Au99.99   — spot 99.99% purity
    Au(T+D)   — deferred-delivery (most liquid, think "Shanghai benchmark")
    mAu(T+D)  — mini deferred
    Au100g    — 100g bars
    Ag(T+D)   — silver deferred

Metrics extracted per contract:
    close, volume_kg, open_interest_lots, delivery_volume_lots

Why: Chinese retail + PBOC buying has been the dominant marginal bid for gold
since 2022. SGE withdrawals ≈ Chinese demand proxy.

Note: The page is HTML with a table. We parse via BeautifulSoup.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List

import pandas as pd
from bs4 import BeautifulSoup

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import http_get

CONTRACTS_WE_WANT = {"Au99.99", "Au(T+D)", "mAu(T+D)", "Au100g", "Ag(T+D)", "Au99.95"}


class SgeConnector(BaseConnector):
    meta = ConnectorMeta(
        name="sge",
        category="physical",
        frequency="daily",
        requires_key=False,
        description="Shanghai Gold Exchange daily report (spot + T+D)",
    )

    BASE = "https://en.sge.com.cn/data/data_daily_international_new"

    def _fetch_month(self, start: date, end: date) -> List[dict]:
        params = {"start_date": start.isoformat(), "end_date": end.isoformat()}
        r = http_get(self.BASE, params=params, headers={
            "User-Agent": "Mozilla/5.0 (QuantFlow-Gold/0.1)",
            "Accept-Language": "en",
        })
        soup = BeautifulSoup(r.text, "lxml")
        table = soup.find("table")
        if not table:
            return []

        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        rows = []
        for tr in table.find_all("tr")[1:]:
            tds = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(tds) < 8:
                continue
            row = dict(zip(headers, tds))
            rows.append(row)
        return rows

    def fetch(self, start: str = "2024-01-01", end: str | None = None) -> pd.DataFrame:
        start_d = pd.Timestamp(start).date()
        end_d = pd.Timestamp(end).date() if end else date.today()

        all_rows: list[dict] = []
        # Iterate month by month (endpoint limits to ~1 month range)
        cursor = start_d
        while cursor <= end_d:
            chunk_end = min(cursor + timedelta(days=28), end_d)
            try:
                all_rows.extend(self._fetch_month(cursor, chunk_end))
            except Exception as e:  # noqa: BLE001
                from loguru import logger
                logger.warning(f"[sge] {cursor}..{chunk_end} failed: {e}")
            cursor = chunk_end + timedelta(days=1)

        if not all_rows:
            return pd.DataFrame()

        out = []
        for row in all_rows:
            contract = row.get("Contract") or row.get("合约")
            if contract not in CONTRACTS_WE_WANT:
                continue
            # Normalize the contract name for the metric prefix
            pfx = (
                contract.replace("(", "").replace(")", "").replace("+", "_plus_")
                .replace(".", "_").replace(" ", "_").lower()
            )
            date_str = row.get("Date")
            if not date_str:
                continue

            def f(key, scale=1.0):
                v = row.get(key, "").replace(",", "").strip()
                if v in ("", "-"):
                    return None
                try:
                    return float(v) * scale
                except ValueError:
                    return None

            mapping = {
                f"sge_{pfx}_close_cny_per_g":   (f("Close"),               "cny/g"),
                f"sge_{pfx}_volume_kg":         (f("Volume(Kg)"),          "kg"),
                f"sge_{pfx}_amount_cny":        (f("Amount(yuan)"),        "cny"),
                f"sge_{pfx}_open_interest_lots":(f("OpenInterest(Lot)"),   "lots"),
                f"sge_{pfx}_delivery_lots":     (f("DeliveryVolume(Lot)"), "lots"),
            }
            for metric, (val, unit) in mapping.items():
                if val is None:
                    continue
                out.append({
                    "date": date_str,
                    "metric": metric,
                    "value": val,
                    "unit": unit,
                    "contract": contract,
                })
        return pd.DataFrame(out)
