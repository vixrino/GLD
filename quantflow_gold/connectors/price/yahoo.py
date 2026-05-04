"""Yahoo Finance — OHLCV for gold futures, miners, cross-assets.

We use `yfinance` which scrapes Yahoo's JSON chart API. 100% free, no key.

Tickers are grouped by role so the quants can easily see what we give them:

  gold_futures   — GC=F (Gold front), MGC=F (micro gold), SI=F (Silver)
  metals         — HG=F (Copper), PL=F (Platinum), PA=F (Palladium)
  energy         — CL=F (WTI crude), NG=F (natgas)
  fx             — DX-Y.NYB (DXY index), USDJPY=X, EURUSD=X, USDCNY=X
  rates          — ^TNX (10y nominal), ^IRX (3M T-bill)
  vol            — ^VIX, ^GVZ (Gold VIX), ^MOVE (via ICE BofA on FRED normally)
  crypto         — BTC-USD, ETH-USD
  gold_etfs      — GLD, IAU, GLDM, SGOL, BAR, PHYS, OUNZ
  silver_etfs    — SLV, SIVR
  miner_etfs     — GDX, GDXJ, SIL, SILJ, RING
  majors         — NEM, GOLD (Barrick), AEM (Agnico), FNV, WPM, KGC, GFI, AU
  silver_miners  — PAAS, HL, FSM, AG, EXK
  small_caps     — HMY, IAG, EGO, NGD, OR, SAND

Output: one row per (date, metric). Metrics are named `<ticker_slug>_<field>`
(fields: open, high, low, close, adjclose, volume).
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta


TICKERS: dict[str, str] = {
    # --- gold / silver futures ---
    "GC=F":   "gold_futures_front",
    "MGC=F":  "micro_gold_futures",
    "SI=F":   "silver_futures_front",
    "SIL=F":  "micro_silver_futures",
    # --- other metals ---
    "HG=F":   "copper_futures",
    "PL=F":   "platinum_futures",
    "PA=F":   "palladium_futures",
    # --- energy ---
    "CL=F":   "wti_crude",
    "NG=F":   "natgas",
    # --- FX ---
    "DX-Y.NYB": "dxy",
    "JPY=X":    "usdjpy",
    "EURUSD=X": "eurusd",
    "CNY=X":    "usdcny",
    "INR=X":    "usdinr",
    "TRY=X":    "usdtry",
    # --- rates ---
    "^TNX":   "us10y_yield",
    "^IRX":   "us3m_yield",
    "^FVX":   "us5y_yield",
    "^TYX":   "us30y_yield",
    # --- vol ---
    "^VIX":   "vix",
    "^GVZ":   "gold_vix",
    "^OVX":   "oil_vix",
    # --- crypto (inflation hedge narrative) ---
    "BTC-USD": "bitcoin",
    "ETH-USD": "ether",
    "PAXG-USD": "paxg",
    # --- gold ETFs ---
    "GLD":    "gld",
    "IAU":    "iau",
    "GLDM":   "gldm",
    "SGOL":   "sgol",
    "BAR":    "bar_etf",
    "PHYS":   "phys_sprott",
    "OUNZ":   "ounz",
    # --- silver ETFs ---
    "SLV":    "slv",
    "SIVR":   "sivr",
    # --- miner ETFs ---
    "GDX":    "gdx",
    "GDXJ":   "gdxj",
    "SIL":    "sil_etf",
    "SILJ":   "silj",
    "RING":   "ring",
    "NUGT":   "nugt_3x",
    "JNUG":   "jnug_3x",
    # --- major miners ---
    "NEM":    "newmont",
    "GOLD":   "barrick",
    "AEM":    "agnico_eagle",
    "FNV":    "franco_nevada",
    "WPM":    "wheaton_precious",
    "KGC":    "kinross",
    "GFI":    "gold_fields",
    "AU":     "anglogold",
    "AGI":    "alamos",
    # --- silver miners ---
    "PAAS":   "pan_american_silver",
    "HL":     "hecla",
    "FSM":    "fortuna_silver",
    "AG":     "first_majestic",
    "EXK":    "endeavour_silver",
    # --- small caps / royalty ---
    "HMY":    "harmony",
    "IAG":    "iamgold",
    "EGO":    "eldorado",
    "NGD":    "new_gold",
    "OR":     "osisko_royalties",
    "SAND":   "sandstorm_gold",
    # --- equity benchmarks (cross-asset) ---
    "^GSPC":  "sp500",
    "^NDX":   "nasdaq100",
    "^STOXX50E": "eurostoxx50",
    "^HSI":   "hang_seng",
    "000001.SS": "shanghai_composite",
}

FIELDS = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]


class YahooConnector(BaseConnector):
    meta = ConnectorMeta(
        name="yahoo",
        category="price",
        frequency="daily",
        requires_key=False,
        description="Yahoo Finance OHLCV: gold & silver futures, miners, FX, rates, vol, crypto",
    )

    def _download(self, tickers: Iterable[str], start: str, end: str | None) -> pd.DataFrame:
        import yfinance as yf
        data = yf.download(
            tickers=list(tickers),
            start=start,
            end=end,
            interval="1d",
            auto_adjust=False,
            progress=False,
            group_by="ticker",
            threads=True,
        )
        return data

    def fetch(self, start: str = "1996-01-01", end: str | None = None) -> pd.DataFrame:
        from loguru import logger

        data = self._download(TICKERS.keys(), start, end)
        if data is None or data.empty:
            logger.warning("[yahoo] no data returned")
            return pd.DataFrame()

        rows: list[dict] = []
        for ticker, slug in TICKERS.items():
            try:
                sub = data[ticker].dropna(how="all")
            except KeyError:
                logger.debug(f"[yahoo] {ticker} absent from response")
                continue
            if sub.empty:
                continue
            for field in FIELDS:
                if field not in sub.columns:
                    continue
                series = sub[field].dropna()
                if series.empty:
                    continue
                field_slug = field.lower().replace(" ", "_")
                for dt, val in series.items():
                    try:
                        val = float(val)
                    except (ValueError, TypeError):
                        continue
                    rows.append({
                        "date": pd.Timestamp(dt).to_pydatetime(),
                        "metric": f"{slug}_{field_slug}",
                        "value": val,
                        "unit": "usd" if field_slug != "volume" else "shares",
                        "ticker": ticker,
                    })
        return pd.DataFrame(rows)
