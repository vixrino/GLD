"""FRED (St. Louis Fed) — all the macro drivers that move gold.

Doc: https://fred.stlouisfed.org/docs/api/fred/
API key is free, unlimited calls in practice.

We pull the series that the quants will almost certainly want:
- Real yields (10y TIPS)
- Nominal yields (DGS10, DGS2, DGS30)
- Breakevens (T10YIE, T5YIE)
- DXY (trade-weighted dollar)
- Fed Funds effective
- CPI (headline + core)
- M2, Fed balance sheet (WALCL)
- Unemployment, PMI proxy
- Gold London PM fix (GOLDPMGBD228NLBM) — free gold history since 1968
- TED spread, financial stress indices

Add or remove series freely. The source-of-truth for series IDs is
https://fred.stlouisfed.org/.
"""

from __future__ import annotations

import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import env, http_get

SERIES = {
    # Real / nominal yields — the #1 macro driver of gold
    "DFII10":           ("real_yield_10y",           "pct"),
    "DFII5":            ("real_yield_5y",            "pct"),
    "DFII30":           ("real_yield_30y",           "pct"),
    "DGS10":            ("nominal_yield_10y",        "pct"),
    "DGS2":             ("nominal_yield_2y",         "pct"),
    "DGS30":            ("nominal_yield_30y",        "pct"),
    "T10YIE":           ("breakeven_10y",            "pct"),
    "T5YIE":            ("breakeven_5y",             "pct"),
    "T10Y2Y":           ("yield_curve_10y2y",        "pct"),

    # USD — second biggest driver
    "DTWEXBGS":         ("dxy_broad_tw",             "index"),
    "DEXUSEU":          ("usd_eur",                  "rate"),
    "DEXJPUS":          ("jpy_usd",                  "rate"),
    "DEXCHUS":          ("cny_usd",                  "rate"),
    "DEXINUS":          ("inr_usd",                  "rate"),

    # Rates / Fed
    "DFF":              ("fed_funds_effective",      "pct"),
    "SOFR":             ("sofr",                     "pct"),
    "FEDFUNDS":         ("fed_funds_monthly",        "pct"),

    # Inflation
    "CPIAUCSL":         ("cpi_headline_sa",          "index"),
    "CPILFESL":         ("cpi_core_sa",              "index"),
    "PCEPI":            ("pce_headline",             "index"),
    "PCEPILFE":         ("pce_core",                 "index"),

    # Fed balance sheet / liquidity
    "WALCL":            ("fed_balance_sheet",        "mln_usd"),
    "M2SL":             ("m2_money_supply",          "bln_usd"),
    "RRPONTSYD":        ("fed_rrp",                  "bln_usd"),
    "WTREGEN":          ("treasury_general_account", "bln_usd"),

    # Stress / vol
    "VIXCLS":           ("vix",                      "index"),
    "STLFSI4":          ("stlouis_financial_stress", "index"),
    "BAMLHE00EHYITRIV": ("hy_credit_spread",         "bps"),

    # Macro context
    "UNRATE":           ("unemployment_rate",        "pct"),
    "INDPRO":           ("industrial_production",    "index"),

    # Gold itself (free long history from LBMA via FRED)
    "GOLDPMGBD228NLBM": ("gold_london_pm_fix",       "usd/oz"),
    "GOLDAMGBD228NLBM": ("gold_london_am_fix",       "usd/oz"),
}


class FredConnector(BaseConnector):
    meta = ConnectorMeta(
        name="fred",
        category="macro",
        frequency="daily",
        requires_key=True,
        description="FRED: real yields, DXY, CPI, Fed balance sheet, gold fix, etc.",
    )

    BASE = "https://api.stlouisfed.org/fred/series/observations"

    def fetch(self, start: str = "2010-01-01") -> pd.DataFrame:
        api_key = env("FRED_API_KEY", required=True)
        out = []
        for series_id, (metric, unit) in SERIES.items():
            params = {
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "observation_start": start,
            }
            try:
                r = http_get(self.BASE, params=params)
                obs = r.json().get("observations", [])
            except Exception as e:  # noqa: BLE001
                from loguru import logger
                logger.warning(f"[fred] skip {series_id}: {e}")
                continue
            for o in obs:
                if o["value"] == ".":
                    continue
                out.append({
                    "date": o["date"],
                    "metric": metric,
                    "value": float(o["value"]),
                    "unit": unit,
                    "fred_series_id": series_id,
                })
        return pd.DataFrame(out)
