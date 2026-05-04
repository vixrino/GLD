"""Long-history gold price in multiple currencies (no API key required).

Stooq (the original primary) now sits behind a captcha-gated API key. This
connector now combines two robust free sources:

1. FRED public CSV endpoint  — daily LBMA Gold PM/AM fix (1968-04-01 +) and
   FX series we use to derive cross-currency gold prices.
   No API key required:  https://fred.stlouisfed.org/graph/fredgraph.csv?id=...

2. Yahoo Finance gold-backed ETFs (yfinance) — direct cross-currency gold
   exposure for the last 5+ years. Used as a fallback when FRED is slow.

We then derive Gold/oz in each currency:
- gold_eur_oz = USD_gold / DEXUSEU
- gold_gbp_oz = USD_gold / DEXUSUK
- gold_aud_oz = USD_gold / DEXUSAL
- gold_jpy_oz = USD_gold * DEXJPUS
- gold_cny_oz = USD_gold * DEXCHUS
- gold_inr_oz = USD_gold * DEXINUS
- gold_chf_oz = USD_gold * DEXSZUS
- gold_cad_oz = USD_gold * DEXCAUS
- gold_thb_oz = USD_gold * DEXTHUS
- gold_krw_oz = USD_gold * DEXKOUS

Cross-currency gold series are useful for:
- Backtests for non-US trading desks
- Cross-asset signals (gold vs local-currency strength)
- Detecting regime divergence (gold rallying in TRY/INR while flat in USD)
"""

from __future__ import annotations

import io

import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import http_get


GOLD_SERIES = {
    "GOLDPMGBD228NLBM": ("gold_london_pm_fix_usd",  "usd/oz"),
    "GOLDAMGBD228NLBM": ("gold_london_am_fix_usd",  "usd/oz"),
}

# (target ccy, mode, friendly fx_metric)
#   "div" → gold / fx  (FRED is USD per FX-currency, so divide to convert)
#   "mul" → gold * fx  (FRED is FX-currency per USD, so multiply)
FX_SERIES: dict[str, tuple[str, str, str]] = {
    "DEXUSEU": ("eur", "div", "usd_per_eur"),
    "DEXUSUK": ("gbp", "div", "usd_per_gbp"),
    "DEXUSAL": ("aud", "div", "usd_per_aud"),
    "DEXJPUS": ("jpy", "mul", "jpy_per_usd"),
    "DEXCHUS": ("cny", "mul", "cny_per_usd"),
    "DEXINUS": ("inr", "mul", "inr_per_usd"),
    "DEXSZUS": ("chf", "mul", "chf_per_usd"),
    "DEXCAUS": ("cad", "mul", "cad_per_usd"),
    "DEXTHUS": ("thb", "mul", "thb_per_usd"),
    "DEXKOUS": ("krw", "mul", "krw_per_usd"),
}

# Cross-currency gold ETFs (Yahoo) used as fallback when FRED is unreachable.
# The currency reported by Yahoo `Ticker.info["currency"]` is included as a
# safety check; `unit_override` is what we publish in our schema.
ETF_FALLBACK: dict[str, tuple[str, str, str]] = {
    "PHGP.L":  ("gold_etf_gbp",  "gbp/share",   "GBp"),  # Wisdom-Tree Physical Gold (GBp)
    "EGLN.L":  ("gold_etf_eur",  "eur/share",   "EUR"),  # iShares Physical Gold (EUR)
    "4GLD.DE": ("gold_etf_eur2", "eur/share",   "EUR"),  # Xetra-Gold
    "PHAU.L":  ("gold_etf_usd",  "usd/share",   "USD"),  # WisdomTree Physical Gold (USD)
    "SGLD.L":  ("gold_etf_usd2", "usd/share",   "USD"),  # iShares Physical Gold ETC (USD)
    "GLD":     ("gld_us",        "usd/share",   "USD"),
    "IAU":     ("iau_us",        "usd/share",   "USD"),
}


class HistoricalLongConnector(BaseConnector):
    meta = ConnectorMeta(
        name="historical_long",
        category="price",
        frequency="daily",
        requires_key=False,
        description="Long-history gold (USD + 10 cross-currency derivations) via FRED CSV + Yahoo ETFs",
    )

    BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"

    def _fetch_series(self, series_id: str, start: str) -> pd.Series:
        from loguru import logger
        try:
            r = http_get(
                self.BASE,
                params={"id": series_id, "cosd": start},
                headers={"User-Agent": "Mozilla/5.0 (compatible; QuantFlow-Gold/0.1)"},
                timeout=20.0,
                retries=1,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[historical_long] fetch {series_id} failed: {e}")
            return pd.Series(dtype="float64")

        text = r.text.strip()
        if not text or "<html" in text[:200].lower():
            return pd.Series(dtype="float64")

        try:
            df = pd.read_csv(io.StringIO(text))
        except Exception:
            return pd.Series(dtype="float64")

        date_col = next((c for c in df.columns if c.lower() in ("observation_date", "date")), None)
        val_col = next((c for c in df.columns if c != date_col), None)
        if date_col is None or val_col is None:
            return pd.Series(dtype="float64")

        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
        df = df.dropna(subset=[date_col]).set_index(date_col)
        return df[val_col].dropna().rename(series_id)

    def _yahoo_fallback(self, start: str) -> list[dict]:
        """Pull gold-backed ETFs from Yahoo Finance as a robust fallback."""
        from loguru import logger
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("[historical_long] yfinance not installed; skipping fallback")
            return []

        rows: list[dict] = []
        for ticker, (slug, unit, expected_ccy) in ETF_FALLBACK.items():
            try:
                hist = yf.Ticker(ticker).history(start=start, auto_adjust=False)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[historical_long] yahoo {ticker} failed: {e}")
                continue
            if hist is None or hist.empty:
                continue
            for date, row in hist.iterrows():
                d = pd.Timestamp(date).tz_localize(None) if pd.Timestamp(date).tzinfo else pd.Timestamp(date)
                for col in ("Open", "High", "Low", "Close"):
                    v = row.get(col)
                    if pd.isna(v):
                        continue
                    rows.append({
                        "date": d,
                        "metric": f"{slug}_{col.lower()}",
                        "value": float(v),
                        "unit": unit,
                        "yahoo_ticker": ticker,
                        "yahoo_currency": expected_ccy,
                    })
                vol = row.get("Volume")
                if pd.notna(vol):
                    rows.append({
                        "date": d,
                        "metric": f"{slug}_volume",
                        "value": float(vol),
                        "unit": "share",
                        "yahoo_ticker": ticker,
                    })
        return rows

    def fetch(self, start: str = "1968-01-01") -> pd.DataFrame:
        from loguru import logger
        rows: list[dict] = []

        # 1. USD gold via FRED CSV
        gold_pm = self._fetch_series("GOLDPMGBD228NLBM", start)
        gold_am = self._fetch_series("GOLDAMGBD228NLBM", start)
        for series_id, series in [("GOLDPMGBD228NLBM", gold_pm), ("GOLDAMGBD228NLBM", gold_am)]:
            metric, unit = GOLD_SERIES[series_id]
            for date, val in series.items():
                rows.append({
                    "date": date,
                    "metric": metric,
                    "value": float(val),
                    "unit": unit,
                    "fred_series_id": series_id,
                })

        # 2. Cross-currency gold derived from FRED FX rates (only if USD gold present)
        if not gold_pm.empty:
            for fx_id, (ccy, mode, fx_metric) in FX_SERIES.items():
                fx = self._fetch_series(fx_id, start)
                if fx.empty:
                    continue

                for date, val in fx.items():
                    rows.append({
                        "date": date,
                        "metric": fx_metric,
                        "value": float(val),
                        "unit": "rate",
                        "fred_series_id": fx_id,
                    })

                joined = pd.concat([gold_pm.rename("gold"), fx.rename("fx")], axis=1, join="inner").dropna()
                gold_local = (joined["gold"] * joined["fx"]) if mode == "mul" else (joined["gold"] / joined["fx"])

                metric_name = f"gold_pm_fix_{ccy}"
                unit = f"{ccy}/oz"
                for date, val in gold_local.items():
                    if pd.isna(val):
                        continue
                    rows.append({
                        "date": date,
                        "metric": metric_name,
                        "value": float(val),
                        "unit": unit,
                        "fred_series_id": f"{fx_id}+GOLDPMGBD228NLBM",
                    })
        else:
            logger.warning("[historical_long] FRED USD gold unavailable; skipping cross-currency derivations")

        # 3. Always run the Yahoo ETF fallback — gives 5y of cross-currency gold
        #    even if FRED is slow / unreachable, and is independent of the FRED
        #    derivations above.
        yahoo_start = max(start, "2005-01-01")
        rows.extend(self._yahoo_fallback(yahoo_start))

        return pd.DataFrame(rows)
