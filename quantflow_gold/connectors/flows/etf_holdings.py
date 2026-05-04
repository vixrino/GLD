"""Gold ETF flow proxies — daily.

Background:
   In late 2025 SPDR (GLD) migrated to a Next.js site and dropped the public
   `GLD_US_archive_EN.csv` historical-tonnes feed. iShares similarly removed
   public IAU CSV downloads. The World Gold Council aggregator file behind a
   Cloudflare-protected URL refuses programmatic access (403).

Working free sources we can actually rely on right now:
   1) Yahoo Finance OHLCV for the gold ETF tickers (GLD, IAU, GLDM, SGOL,
      BAR, PHYS, OUNZ). Volume × close → daily $-flow proxy. Sustained
      heavy volume on negative drift = redemption (creation/redemption is the
      mechanism by which physical gold enters/exits the trust).
   2) SEC EDGAR XBRL — SPDR Gold Trust (CIK 0001222333) and iShares Gold Trust
      (CIK 0001222333 / 0001327068) file 10-K and 10-Q quarterly. Their
      financial statements include exact "Ounces of gold" held in trust as a
      US-GAAP custom tag (sometimes `InvestmentInGoldHeld`,
      `GoldInventoryOuncesHeldInTrust`). We pull all numeric XBRL facts and
      surface anything that looks like ounces.

Output:
   etf_<ticker>_volume_shares      (daily, from yahoo)
   etf_<ticker>_close_usd          (daily)
   etf_<ticker>_dollar_volume      (volume * close, $ flow proxy)
   etf_<ticker>_aum_usd_yf         (yfinance "totalAssets" point estimate)
   gld_trust_oz_xbrl               (from SEC EDGAR, quarterly, authoritative)
   iau_trust_oz_xbrl               (from SEC EDGAR, quarterly)

Note: when SPDR / iShares restore public CSV feeds, add the URL fetch back
into `_fetch_spdr_csv()` as the primary source.
"""

from __future__ import annotations

import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import env, http_get


GOLD_ETFS = ["GLD", "IAU", "GLDM", "SGOL", "BAR", "PHYS", "OUNZ", "AAAU"]
SILVER_ETFS = ["SLV", "SIVR", "PSLV"]
MINER_ETFS = ["GDX", "GDXJ", "RING", "SIL", "SILJ"]

# SEC EDGAR CIK numbers
TRUSTS = {
    "gld":  ("0001222333", "spdr_gold_trust"),
    "iau":  ("0001327068", "ishares_gold_trust"),
    "sivr": ("0001459242", "aberdeen_silver_trust"),
}


class EtfHoldingsConnector(BaseConnector):
    meta = ConnectorMeta(
        name="etf_holdings",
        category="flows",
        frequency="daily",
        requires_key=False,
        description="Gold ETF flow proxies (Yahoo OHLCV + SEC EDGAR trust filings)",
    )

    def _fetch_yfinance_flows(self) -> pd.DataFrame:
        from loguru import logger
        try:
            import yfinance as yf
        except ImportError:
            logger.error("[etf_holdings] yfinance not installed")
            return pd.DataFrame()

        tickers = GOLD_ETFS + SILVER_ETFS + MINER_ETFS
        try:
            data = yf.download(
                tickers=tickers,
                start="2010-01-01",
                interval="1d",
                auto_adjust=False,
                progress=False,
                group_by="ticker",
                threads=True,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[etf_holdings] yf.download failed: {e}")
            return pd.DataFrame()
        if data is None or data.empty:
            return pd.DataFrame()

        rows: list[dict] = []
        for t in tickers:
            try:
                sub = data[t].dropna(how="all")
            except KeyError:
                continue
            if sub.empty or "Close" not in sub.columns or "Volume" not in sub.columns:
                continue
            slug = t.lower()
            for dt, row in sub.iterrows():
                close = row.get("Close")
                vol = row.get("Volume")
                if pd.isna(close) or pd.isna(vol):
                    continue
                try:
                    close_f = float(close)
                    vol_f = float(vol)
                except (TypeError, ValueError):
                    continue
                rows.append({"date": pd.Timestamp(dt), "metric": f"etf_{slug}_close_usd", "value": close_f, "unit": "usd"})
                rows.append({"date": pd.Timestamp(dt), "metric": f"etf_{slug}_volume_shares", "value": vol_f, "unit": "shares"})
                rows.append({"date": pd.Timestamp(dt), "metric": f"etf_{slug}_dollar_volume", "value": close_f * vol_f, "unit": "usd"})
        return pd.DataFrame(rows)

    def _fetch_edgar_trust_oz(self) -> pd.DataFrame:
        from loguru import logger
        ua = {"User-Agent": env("SEC_USER_AGENT", default="QuantFlow Gold ops@example.com")}
        rows: list[dict] = []
        for short, (cik, slug) in TRUSTS.items():
            url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
            try:
                r = http_get(url, headers=ua)
                facts = r.json().get("facts", {})
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[etf_holdings] EDGAR {short}/{cik}: {e}")
                continue

            for taxonomy_name in ("us-gaap", "ifrs-full", "dei"):
                taxonomy = facts.get(taxonomy_name, {})
                for tag_name, tag in taxonomy.items():
                    units = tag.get("units", {})
                    for unit_name, vals in units.items():
                        if not any(k in unit_name.lower() for k in ("oz", "troy", "ounce")):
                            continue
                        for v in vals:
                            end = v.get("end")
                            val = v.get("val")
                            if end is None or val is None:
                                continue
                            try:
                                rows.append({
                                    "date": pd.Timestamp(end),
                                    "metric": f"{short}_trust_{tag_name.lower()}_{unit_name.lower()}",
                                    "value": float(val),
                                    "unit": unit_name.lower(),
                                    "trust": slug,
                                    "form": v.get("form"),
                                    "fp": v.get("fp"),
                                    "fy": v.get("fy"),
                                })
                            except (TypeError, ValueError):
                                continue
            # Also surface "Assets" or "InvestmentInGold" which gives the AUM in USD
            tag_for_aum = facts.get("us-gaap", {}).get("Assets")
            if tag_for_aum:
                for unit_name, vals in tag_for_aum.get("units", {}).items():
                    for v in vals:
                        end = v.get("end")
                        val = v.get("val")
                        if end is None or val is None:
                            continue
                        try:
                            rows.append({
                                "date": pd.Timestamp(end),
                                "metric": f"{short}_trust_assets",
                                "value": float(val),
                                "unit": unit_name.lower(),
                                "trust": slug,
                                "form": v.get("form"),
                                "fp": v.get("fp"),
                                "fy": v.get("fy"),
                            })
                        except (TypeError, ValueError):
                            continue
        return pd.DataFrame(rows)

    def fetch(self) -> pd.DataFrame:
        from loguru import logger
        parts: list[pd.DataFrame] = []
        try:
            yf_df = self._fetch_yfinance_flows()
            if not yf_df.empty:
                logger.info(f"[etf_holdings] yfinance: {len(yf_df):,} rows")
                parts.append(yf_df)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[etf_holdings] yfinance section failed: {e}")
        try:
            edgar_df = self._fetch_edgar_trust_oz()
            if not edgar_df.empty:
                logger.info(f"[etf_holdings] EDGAR XBRL: {len(edgar_df):,} rows")
                parts.append(edgar_df)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[etf_holdings] EDGAR section failed: {e}")
        if not parts:
            return pd.DataFrame()
        return pd.concat(parts, ignore_index=True)
