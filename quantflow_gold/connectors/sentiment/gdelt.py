"""GDELT 2.0 Doc API — global news sentiment on gold-related topics.

Doc: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
No auth required. Rate limits are generous for research use.

We bypass the ``gdeltdoc`` Python client because it forcibly wraps the
``keyword`` argument in extra quotes, which breaks valid GDELT boolean
queries (e.g. unbalanced parentheses, double-quoting, "keyword too short"
errors). Instead we build the query URL ourselves — straightforward GET
to ``api.gdeltproject.org/api/v2/doc/doc``.

Query rules (as of 2026):
  - phrases must be 2-5 words and wrapped in double quotes
  - single keywords must be >= 3 chars
  - boolean ``OR`` and parentheses supported, must be balanced
  - filters appended as ``sourcelang:english`` etc.

Modes we extract:
  - ``timelinevolraw``   daily article count for the query
  - ``timelinetone``     daily mean tone (-10 very negative, +10 very positive)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
from loguru import logger

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import http_get


_API = "https://api.gdeltproject.org/api/v2/doc/doc"

QUERIES: dict[str, str] = {
    "gold_price":          '("gold price" OR "price of gold")',
    "central_bank_gold":   '"central bank" gold',
    "gold_reserves":       '"gold reserves"',
    "inflation_hedge":     '("inflation hedge" OR "hedge against inflation")',
    "dollar_collapse":     '("dollar collapse" OR dedollarization)',
    "mine_disruption":     'gold (strike OR closure OR flood)',
    "bullion":             'bullion gold',
    "gold_china":          '"gold reserves" China',
    "gold_russia":         '"gold reserves" Russia',
    "gold_india":          '"gold imports" India',
    "safe_haven":          '"safe haven" gold',
}


class GdeltConnector(BaseConnector):
    meta = ConnectorMeta(
        name="gdelt",
        category="sentiment",
        frequency="daily",
        requires_key=False,
        description="GDELT 2.0 Doc API — news volume + tone on gold-related queries",
    )

    def _query(self, q: str, mode: str, start: date, end: date) -> pd.DataFrame:
        params: dict[str, Any] = {
            "query": f"{q} sourcelang:english",
            "mode": mode,
            "format": "json",
            "startdatetime": start.strftime("%Y%m%d000000"),
            "enddatetime":   end.strftime("%Y%m%d000000"),
            "maxrecords": 250,
            "timezoom": "yes",
        }
        try:
            r = http_get(_API, params=params, timeout=20.0, retries=2)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"http_error: {e}") from e

        text = r.text.strip()
        if not text:
            return pd.DataFrame()
        if text.startswith("<") or "error" in text.lower()[:200] and not text.startswith("{"):
            raise RuntimeError(f"api_error: {text[:200]}")
        try:
            payload = r.json()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"bad_json: {e}; body[:200]={text[:200]}") from e

        timeline = payload.get("timeline") or []
        if not timeline:
            return pd.DataFrame()
        series = timeline[0].get("data", [])
        if not series:
            return pd.DataFrame()
        df = pd.DataFrame(series)
        if "date" not in df.columns or "value" not in df.columns:
            return pd.DataFrame()
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df.dropna(subset=["value"])

    def fetch(self, days_back: int = 365 * 3) -> pd.DataFrame:
        end_d = date.today()
        start_d = end_d - timedelta(days=days_back)

        rows: list[dict] = []
        for slug, query in QUERIES.items():
            for mode, unit in (("timelinevolraw", "n_articles"), ("timelinetone", "tone")):
                try:
                    df = self._query(query, mode, start_d, end_d)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[gdelt] {slug}/{mode}: {e}")
                    continue
                if df.empty:
                    continue
                metric_suffix = "vol" if mode == "timelinevolraw" else "tone"
                for _, r in df.iterrows():
                    rows.append({
                        "date": r["date"],
                        "metric": f"gdelt_{slug}_{metric_suffix}",
                        "value": float(r["value"]),
                        "unit": unit,
                        "query": query,
                    })

        out = pd.DataFrame(rows)
        if out.empty:
            logger.warning("[gdelt] all queries returned empty")
        else:
            logger.info(
                f"[gdelt] {len(out)} rows across {out['metric'].nunique()} metrics"
            )
        return out
