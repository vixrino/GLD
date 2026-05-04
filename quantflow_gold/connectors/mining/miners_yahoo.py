"""Miners performance / ratios — derived from Yahoo data.

This connector does NOT re-download; it reads the yahoo parquet we already
wrote (`data/processed/yahoo/latest.parquet`) and computes *derived* series the
quants love for gold:

  - gdx_gld_ratio          — miners vs physical (leading indicator)
  - gdxj_gdx_ratio         — junior vs senior miners risk appetite
  - sil_slv_ratio          — silver miners vs silver
  - gold_silver_ratio      — XAU/XAG
  - gold_copper_ratio      — fear/growth
  - gold_oil_ratio         — real / commodity index proxy
  - gold_sp500_ratio       — gold vs equities
  - nem_gold_beta_90d      — rolling beta of NEM to gold
  - miners_relative_strength — GDX return - GLD return (rolling 20d)

Output feeds the same canonical long schema.

If the upstream yahoo parquet is not yet present, the connector returns empty
(run `run.py --source yahoo` first, or `run.py --all`).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta


def _load_yahoo(data_dir: Path) -> pd.DataFrame:
    p = data_dir / "processed" / "yahoo" / "latest.parquet"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p)


def _pivot_close(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    closes = df[df["metric"].str.endswith("_close")].copy()
    closes["instrument"] = closes["metric"].str.replace("_close$", "", regex=True)
    wide = closes.pivot_table(index="date", columns="instrument", values="value", aggfunc="last")
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()


class MinersYahooConnector(BaseConnector):
    meta = ConnectorMeta(
        name="miners_yahoo",
        category="mining",
        frequency="daily",
        requires_key=False,
        description="Derived miners/metals ratios and betas from yahoo prices",
    )

    def fetch(self) -> pd.DataFrame:
        from loguru import logger
        raw = _load_yahoo(self.data_dir)
        if raw.empty:
            logger.warning("[miners_yahoo] yahoo latest.parquet not found — run yahoo first")
            return pd.DataFrame()

        px = _pivot_close(raw)
        if px.empty:
            return pd.DataFrame()

        derived: dict[str, pd.Series] = {}

        def safe_ratio(a: str, b: str, name: str):
            if a in px.columns and b in px.columns:
                ratio = px[a] / px[b]
                derived[name] = ratio.dropna()

        safe_ratio("gdx", "gld", "gdx_gld_ratio")
        safe_ratio("gdxj", "gdx", "gdxj_gdx_ratio")
        safe_ratio("sil_etf", "slv", "sil_slv_ratio")
        safe_ratio("silj", "sil_etf", "silj_sil_ratio")
        safe_ratio("gold_futures_front", "silver_futures_front", "gold_silver_ratio")
        safe_ratio("gold_futures_front", "copper_futures", "gold_copper_ratio")
        safe_ratio("gold_futures_front", "wti_crude", "gold_oil_ratio")
        safe_ratio("gold_futures_front", "sp500", "gold_sp500_ratio")
        safe_ratio("gold_futures_front", "bitcoin", "gold_btc_ratio")
        safe_ratio("gold_futures_front", "platinum_futures", "gold_platinum_ratio")

        rets = px.pct_change()
        if "gdx" in rets.columns and "gld" in rets.columns:
            rs = (rets["gdx"] - rets["gld"]).rolling(20).sum()
            derived["miners_relative_strength_20d"] = rs.dropna()

        for miner in ("newmont", "barrick", "agnico_eagle", "kinross"):
            if miner in rets.columns and "gold_futures_front" in rets.columns:
                beta = rets[miner].rolling(90).cov(rets["gold_futures_front"]) / \
                       rets["gold_futures_front"].rolling(90).var()
                derived[f"{miner}_beta_gold_90d"] = beta.dropna()

        rows = []
        for name, series in derived.items():
            for dt, val in series.items():
                if pd.isna(val) or np.isinf(val):
                    continue
                rows.append({
                    "date": dt,
                    "metric": name,
                    "value": float(val),
                    "unit": "ratio" if "ratio" in name else ("beta" if "beta" in name else "ret"),
                })
        return pd.DataFrame(rows)
