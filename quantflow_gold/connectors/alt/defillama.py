"""DefiLlama — stablecoin supply & DeFi TVL.

Rationale: stablecoin total circulation (USDT, USDC, DAI, etc.) is a free,
public proxy for "offshore USD liquidity" — i.e. demand for dollar exposure
outside the US banking system. It has correlated well with gold bull phases
post-2020.

Endpoints (all free, no auth):
    https://stablecoins.llama.fi/stablecoins?includePrices=true
    https://stablecoins.llama.fi/stablecoinprices            (historical peg)
    https://api.llama.fi/v2/historicalChainTvl
    https://api.llama.fi/protocol/paxg                      (PAXG TVL)
    https://api.llama.fi/protocol/tether-gold               (XAUT)

Output series:
    defi_stablecoins_total_supply        (USD)
    defi_stablecoins_<symbol>_supply
    defi_total_tvl                       (USD)
    defi_paxg_tvl
    defi_xaut_tvl
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import http_get


STABLES_URL = "https://stablecoins.llama.fi/stablecoincharts/all"
STABLES_PER_COIN = "https://stablecoins.llama.fi/stablecoins"
CHAIN_TVL_URL = "https://api.llama.fi/v2/historicalChainTvl"

GOLD_TOKENS = ["paxg", "tether-gold"]


class DefiLlamaConnector(BaseConnector):
    meta = ConnectorMeta(
        name="defillama",
        category="alt",
        frequency="daily",
        requires_key=False,
        description="Stablecoin total supply + gold-token TVL (USD offshore liquidity proxy)",
    )

    def _fetch_total_stables_history(self) -> list[dict]:
        r = http_get(STABLES_URL)
        return r.json() or []

    def _fetch_per_coin_snapshot(self) -> list[dict]:
        r = http_get(STABLES_PER_COIN)
        return (r.json() or {}).get("peggedAssets") or []

    def _fetch_chain_tvl_history(self) -> list[dict]:
        r = http_get(CHAIN_TVL_URL)
        return r.json() or []

    def _fetch_protocol(self, slug: str) -> dict:
        r = http_get(f"https://api.llama.fi/protocol/{slug}")
        return r.json() or {}

    def fetch(self) -> pd.DataFrame:
        from loguru import logger
        rows: list[dict] = []

        try:
            hist = self._fetch_total_stables_history()
            for pt in hist:
                ts = pt.get("date")
                if ts is None:
                    continue
                dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
                circ = pt.get("totalCirculatingUSD", {})
                total = 0.0
                if isinstance(circ, dict):
                    for peg_kind, val in circ.items():
                        try:
                            v = float(val)
                        except (ValueError, TypeError):
                            continue
                        total += v
                        rows.append({
                            "date": dt,
                            "metric": f"defi_stablecoins_{peg_kind.lower()}_supply",
                            "value": v,
                            "unit": "usd",
                        })
                if total > 0:
                    rows.append({
                        "date": dt,
                        "metric": "defi_stablecoins_total_supply",
                        "value": total,
                        "unit": "usd",
                    })
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[defillama] stables history failed: {e}")

        try:
            snap = self._fetch_per_coin_snapshot()
            today = datetime.now(timezone.utc).date()
            for coin in snap[:30]:
                sym = (coin.get("symbol") or "").lower()
                if not sym:
                    continue
                circ = (coin.get("circulating") or {}).get("peggedUSD")
                if circ is None:
                    continue
                try:
                    v = float(circ)
                except (ValueError, TypeError):
                    continue
                rows.append({
                    "date": today,
                    "metric": f"defi_stablecoin_{sym}_supply_snapshot",
                    "value": v,
                    "unit": "usd",
                })
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[defillama] per-coin snapshot failed: {e}")

        try:
            tvl_hist = self._fetch_chain_tvl_history()
            for pt in tvl_hist:
                ts = pt.get("date")
                tvl = pt.get("tvl")
                if ts is None or tvl is None:
                    continue
                dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
                rows.append({
                    "date": dt,
                    "metric": "defi_total_tvl",
                    "value": float(tvl),
                    "unit": "usd",
                })
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[defillama] chain tvl failed: {e}")

        for slug in GOLD_TOKENS:
            try:
                proto = self._fetch_protocol(slug)
                series = proto.get("tvl", [])
                for pt in series:
                    ts = pt.get("date")
                    tvl = pt.get("totalLiquidityUSD")
                    if ts is None or tvl is None:
                        continue
                    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
                    rows.append({
                        "date": dt,
                        "metric": f"defi_{slug.replace('-', '_')}_tvl",
                        "value": float(tvl),
                        "unit": "usd",
                    })
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[defillama] {slug} failed: {e}")

        return pd.DataFrame(rows)
