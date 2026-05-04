"""CoinGecko public API — tokenized-gold market caps, supply, and chart history.

Why this is useful:
- PAXG, XAUT and a handful of newer tokens (KAU, DGX, AWG) are 1:1 LBMA gold
  receipts. Their *circulating supply* and *market cap* track real, fee-paying
  bullion stored in custody (Brink's, ICBC Standard, Loomis). Big mint/burn
  events = primary issuance / redemption — i.e. real-world gold delivery.
- Their 24h volume on aggregated venues = global retail / DeFi appetite for
  gold exposure that is orthogonal to ETF flows.
- Combined with the Binance order-book layer (`binance_gold`), we can compute
  PAXG-vs-spot premium, which hits ±1% in periods of physical scarcity and
  is a known macro stress signal.

API:  https://www.coingecko.com/api/documentation
Auth: none (free tier ~10 req/min). Larger plans cost money — we stay free.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import http_get


COINS: dict[str, str] = {
    "pax-gold":     "paxg",
    "tether-gold":  "xaut",
    "kinesis-gold": "kau",
    "aurus-gold":   "awg",
    # The following are sometimes delisted; fetch best-effort:
    "digital-gold-token": "dgx",
    "perth-mint-gold-token": "pmgt",
}


class CoinGeckoGoldConnector(BaseConnector):
    meta = ConnectorMeta(
        name="coingecko_gold",
        category="alt",
        frequency="daily",
        requires_key=False,
        description="CoinGecko gold-token market caps, supply, 24h volume + 90d history",
    )

    SIMPLE = "https://api.coingecko.com/api/v3/simple/price"
    CHART = "https://api.coingecko.com/api/v3/coins/{coin}/market_chart"
    INFO = "https://api.coingecko.com/api/v3/coins/{coin}"

    def fetch(self, days: int = 90) -> pd.DataFrame:
        from loguru import logger
        rows: list[dict] = []
        today = pd.Timestamp(datetime.now(timezone.utc).date())

        coin_ids = ",".join(COINS.keys())

        # 1) Live snapshot — market cap, 24h vol, supply
        try:
            r = http_get(
                self.SIMPLE,
                params={
                    "ids": coin_ids,
                    "vs_currencies": "usd",
                    "include_market_cap": "true",
                    "include_24hr_vol": "true",
                    "include_24hr_change": "true",
                    "include_last_updated_at": "true",
                },
                timeout=15.0,
                retries=2,
            )
            snap = r.json()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[coingecko_gold] simple price failed: {e}")
            snap = {}

        for coin_id, data in snap.items():
            slug = COINS.get(coin_id, coin_id.replace("-", "_"))
            for ck, alias, unit in [
                ("usd",            "price_usd",          "usd"),
                ("usd_market_cap", "market_cap_usd",     "usd"),
                ("usd_24h_vol",    "volume_24h_usd",     "usd"),
                ("usd_24h_change", "change_pct_24h",     "pct"),
            ]:
                v = data.get(ck)
                if v is None:
                    continue
                rows.append({
                    "date": today,
                    "metric": f"{slug}_{alias}",
                    "value": float(v),
                    "unit": unit,
                    "coingecko_id": coin_id,
                })

        # 2) Historical daily for each coin (last N days, free tier)
        for coin_id, slug in COINS.items():
            try:
                r = http_get(
                    self.CHART.format(coin=coin_id),
                    params={"vs_currency": "usd", "days": str(days), "interval": "daily"},
                    timeout=20.0,
                    retries=2,
                )
                payload = r.json()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[coingecko_gold] chart {coin_id} failed: {e}")
                continue

            for series_key, metric_name, unit in [
                ("prices",       f"{slug}_price_usd_d",      "usd"),
                ("market_caps",  f"{slug}_market_cap_usd_d", "usd"),
                ("total_volumes",f"{slug}_volume_usd_d",     "usd"),
            ]:
                for ts_ms, val in payload.get(series_key, []):
                    try:
                        d = pd.to_datetime(ts_ms, unit="ms", utc=True).tz_convert(None)
                        rows.append({
                            "date": d,
                            "metric": metric_name,
                            "value": float(val),
                            "unit": unit,
                            "coingecko_id": coin_id,
                        })
                    except (TypeError, ValueError):
                        continue

            # 3) Supply (circulating / total / max) from /coins endpoint
            try:
                r = http_get(
                    self.INFO.format(coin=coin_id),
                    params={
                        "localization": "false",
                        "tickers": "false",
                        "market_data": "true",
                        "community_data": "false",
                        "developer_data": "false",
                        "sparkline": "false",
                    },
                    timeout=20.0,
                    retries=2,
                )
                info = r.json()
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[coingecko_gold] info {coin_id} failed: {e}")
                info = {}
            md = (info.get("market_data") or {})
            for k, alias, unit in [
                ("circulating_supply", "circulating_supply_oz", "oz"),
                ("total_supply",       "total_supply_oz",       "oz"),
                ("max_supply",         "max_supply_oz",         "oz"),
            ]:
                v = md.get(k)
                if v is None:
                    continue
                try:
                    rows.append({
                        "date": today,
                        "metric": f"{slug}_{alias}",
                        "value": float(v),
                        "unit": unit,
                        "coingecko_id": coin_id,
                    })
                except (TypeError, ValueError):
                    continue

            # CoinGecko free tier: ~10 req/min. Sleep gently between coins.
            time.sleep(0.6)

        return pd.DataFrame(rows)
