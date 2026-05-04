"""StockTwits — per-symbol recent message stream with bullish/bearish tags.

Public endpoint (no auth, rate-limit ~200 req/hour/IP):
    https://api.stocktwits.com/api/2/streams/symbol/{SYMBOL}.json

StockTwits only returns the 30 most recent messages per call. So this is a
"rolling sentiment of the last ~30 messages" — we call it once per run per
symbol. Quants should read it as a *near real-time* pulse, not a full history.

Symbols we poll:
    GLD, IAU, GDX, GDXJ, SLV, SIL, NEM, GOLD, AEM, KGC, GC_F (futures ref)

Metrics per symbol (snapshot at run time):
    stw_<sym>_messages_recent           (count, max 30)
    stw_<sym>_bullish_pct
    stw_<sym>_bearish_pct
    stw_<sym>_unique_users
    stw_<sym>_msg_per_hour_est
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import http_get


SYMBOLS = ["GLD", "IAU", "GDX", "GDXJ", "SLV", "SIL", "NEM", "GOLD", "AEM", "KGC", "FNV", "NUGT"]


class StocktwitsConnector(BaseConnector):
    meta = ConnectorMeta(
        name="stocktwits",
        category="sentiment",
        frequency="daily",
        requires_key=False,
        description="StockTwits live sentiment snapshot for gold-related symbols",
    )

    BASE = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"

    def fetch(self) -> pd.DataFrame:
        from loguru import logger
        now = datetime.now(timezone.utc)
        rows: list[dict] = []

        for sym in SYMBOLS:
            try:
                r = http_get(self.BASE.format(symbol=sym), timeout=15.0, retries=2)
                data = r.json()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[stocktwits] {sym} failed: {e}")
                continue
            msgs = data.get("messages", [])
            if not msgs:
                continue
            n = len(msgs)
            bullish = 0
            bearish = 0
            users = set()
            first_ts, last_ts = None, None
            for m in msgs:
                ent = (m.get("entities") or {}).get("sentiment") or {}
                basic = ent.get("basic")
                if basic == "Bullish":
                    bullish += 1
                elif basic == "Bearish":
                    bearish += 1
                user = (m.get("user") or {}).get("id")
                if user:
                    users.add(user)
                ts = m.get("created_at")
                if ts:
                    try:
                        dt = pd.Timestamp(ts)
                        if first_ts is None or dt < first_ts:
                            first_ts = dt
                        if last_ts is None or dt > last_ts:
                            last_ts = dt
                    except Exception:
                        pass

            date_key = now.date()
            rows.append({"date": date_key, "metric": f"stw_{sym.lower()}_messages_recent",   "value": float(n),                       "unit": "count"})
            rows.append({"date": date_key, "metric": f"stw_{sym.lower()}_bullish_pct",       "value": float(bullish) / n * 100,       "unit": "pct"})
            rows.append({"date": date_key, "metric": f"stw_{sym.lower()}_bearish_pct",       "value": float(bearish) / n * 100,       "unit": "pct"})
            rows.append({"date": date_key, "metric": f"stw_{sym.lower()}_unique_users",      "value": float(len(users)),              "unit": "count"})

            if first_ts and last_ts and last_ts > first_ts:
                hours = max((last_ts - first_ts).total_seconds() / 3600.0, 0.01)
                rate = n / hours
                rows.append({"date": date_key, "metric": f"stw_{sym.lower()}_msgs_per_hour_est", "value": float(rate), "unit": "msg/h"})

            time.sleep(0.5)  # be nice
        return pd.DataFrame(rows)
