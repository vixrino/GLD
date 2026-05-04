"""Binance public REST — tokenized-gold and digital-gold spot data.

Why this connector matters for gold quants:
    - PAXG (Pax Gold) and XAUT (Tether Gold) are 1:1 LBMA-backed tokens.
      Their on-chain price = a real-time, 24/7 retail proxy for spot gold,
      and the basis vs LBMA fix exposes liquidity stress / arbitrage edges.
    - BTC and ETH are routinely cited as "digital gold". Their daily klines
      are useful for cross-asset signals (digital gold vs physical gold flow
      regimes, especially during macro risk-off events).
    - Stablecoin pairs reveal off-shore USD liquidity that affects gold.

Binance publishes a fully open, key-less REST endpoint. Rate limit is generous
(1200 req/min weight), more than enough for daily backfill.

API references:
    - https://binance-docs.github.io/apidocs/spot/en/#kline-candlestick-data
    - https://binance-docs.github.io/apidocs/spot/en/#24hr-ticker-price-change-statistics

Output (canonical long format):
    metric examples
        paxg_usdt_close, paxg_usdt_volume, paxg_usdt_quote_volume,
        xaut_usdt_close, xaut_usdt_volume,
        btc_usdt_close, eth_usdt_close,
    plus snapshot rows for 24h:
        paxg_usdt_premium_to_spot (computed if FRED gold available — left to derived layer)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import http_get


SYMBOLS: dict[str, str] = {
    # Gold-backed tokens
    "PAXGUSDT": "paxg_usdt",
    "XAUTUSDT": "xaut_usdt",
    # "Digital gold" cross-checks
    "BTCUSDT":  "btc_usdt",
    "ETHUSDT":  "eth_usdt",
    # Major reference
    "BNBUSDT":  "bnb_usdt",
}

KLINE_FIELDS = [
    "open_time", "open", "high", "low", "close",
    "volume", "close_time", "quote_volume",
    "trades", "taker_buy_base", "taker_buy_quote", "ignore",
]


class BinanceGoldConnector(BaseConnector):
    meta = ConnectorMeta(
        name="binance_gold",
        category="alt",
        frequency="daily",
        requires_key=False,
        description="Binance public klines — PAXG, XAUT, BTC, ETH (digital + tokenized gold)",
    )

    KLINE_URL = "https://api.binance.com/api/v3/klines"
    TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"

    def _fetch_klines(self, symbol: str, start_ms: int) -> pd.DataFrame:
        """Page through 1000-bar windows until we hit `now`."""
        from loguru import logger
        all_rows: list[list] = []
        cursor = start_ms
        end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        while cursor < end_ms:
            try:
                r = http_get(
                    self.KLINE_URL,
                    params={
                        "symbol": symbol,
                        "interval": "1d",
                        "startTime": cursor,
                        "limit": 1000,
                    },
                    timeout=15.0,
                    retries=2,
                )
                batch = r.json()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[binance_gold] {symbol} batch failed: {e}")
                break
            if not batch:
                break
            all_rows.extend(batch)
            last_open = batch[-1][0]
            if len(batch) < 1000:
                break
            cursor = last_open + 24 * 3600 * 1000  # advance by one day
        if not all_rows:
            return pd.DataFrame()
        df = pd.DataFrame(all_rows, columns=KLINE_FIELDS)
        df["date"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_convert(None)
        for col in ("open", "high", "low", "close", "volume", "quote_volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def _fetch_ticker(self, symbol: str) -> dict:
        try:
            r = http_get(
                self.TICKER_URL,
                params={"symbol": symbol},
                timeout=10.0,
                retries=2,
            )
            return r.json()
        except Exception:  # noqa: BLE001
            return {}

    def fetch(self, start: str = "2019-01-01") -> pd.DataFrame:
        from loguru import logger
        start_ms = int(pd.Timestamp(start).tz_localize("UTC").timestamp() * 1000)
        rows: list[dict] = []

        for symbol, slug in SYMBOLS.items():
            df = self._fetch_klines(symbol, start_ms)
            if df.empty:
                logger.warning(f"[binance_gold] no data for {symbol}")
                continue

            for _, row in df.iterrows():
                rows.append({"date": row["date"], "metric": f"{slug}_open",          "value": row["open"],         "unit": "usdt", "symbol": symbol})
                rows.append({"date": row["date"], "metric": f"{slug}_high",          "value": row["high"],         "unit": "usdt", "symbol": symbol})
                rows.append({"date": row["date"], "metric": f"{slug}_low",           "value": row["low"],          "unit": "usdt", "symbol": symbol})
                rows.append({"date": row["date"], "metric": f"{slug}_close",         "value": row["close"],        "unit": "usdt", "symbol": symbol})
                rows.append({"date": row["date"], "metric": f"{slug}_volume",        "value": row["volume"],       "unit": "base", "symbol": symbol})
                rows.append({"date": row["date"], "metric": f"{slug}_quote_volume",  "value": row["quote_volume"], "unit": "usdt", "symbol": symbol})
                rows.append({"date": row["date"], "metric": f"{slug}_trades",        "value": row["trades"],       "unit": "count","symbol": symbol})

            # 24h snapshot ticker (always today)
            snap = self._fetch_ticker(symbol)
            if snap:
                today = pd.Timestamp(datetime.now(timezone.utc).date())
                for k, alias, unit in [
                    ("priceChange",        "price_change_24h",        "usdt"),
                    ("priceChangePercent", "price_change_pct_24h",    "pct"),
                    ("weightedAvgPrice",   "vwap_24h",                "usdt"),
                    ("lastPrice",          "last_price",              "usdt"),
                    ("highPrice",          "high_24h",                "usdt"),
                    ("lowPrice",           "low_24h",                 "usdt"),
                    ("volume",             "volume_24h",              "base"),
                    ("quoteVolume",        "quote_volume_24h",        "usdt"),
                    ("count",              "trade_count_24h",         "count"),
                ]:
                    v = snap.get(k)
                    if v is None:
                        continue
                    try:
                        val = float(v)
                    except (TypeError, ValueError):
                        continue
                    rows.append({
                        "date": today,
                        "metric": f"{slug}_{alias}",
                        "value": val,
                        "unit": unit,
                        "symbol": symbol,
                    })

        return pd.DataFrame(rows)
