"""Google Trends — retail attention on gold across regions.

Uses `pytrends` (community lib; no official API). Rate-limited: we sleep
between calls and split keywords into batches of 5 (pytrends hard limit).

We pull interest over time for:
  - EN core:  "buy gold", "gold price", "gold crash", "silver squeeze"
  - Macro:    "inflation", "recession", "fed rate", "dollar collapse"
  - FR:       "acheter or", "cours de l'or"
  - ES:       "comprar oro"
  - DE:       "goldpreis"
  - TR:       "altin fiyati"   (huge retail gold market)
  - IN (HI):  "sona bhav"
  - CN (ZH):  "黄金价格"         (best-effort — Google is blocked in CN but
                                  expats + HK searches still informative)

Geo splits:
  US, IN, TR, VN, RU, DE, FR, CN, HK, CA, AU  (major retail gold markets)

NB: Google Trends is normalized 0-100 per query; comparability across regions
needs `pytrends.build_payload(..., geo=XX)` per region. We do it once global
(`geo=""`) and once per major region for spread analysis.
"""

from __future__ import annotations

import time
from typing import Iterable

import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta


def _patch_urllib3_retry_for_pytrends() -> None:
    """pytrends <=4.9.x uses urllib3 v1's `method_whitelist`, removed in v2.

    We wrap ``Retry.__init__`` so it transparently accepts the old kwarg.
    Idempotent and safe on urllib3 v1 too.
    """
    try:
        from urllib3.util.retry import Retry  # type: ignore
    except Exception:  # noqa: BLE001
        return
    if getattr(Retry.__init__, "_qf_patched", False):
        return
    if "method_whitelist" in getattr(Retry.__init__, "__code__", type("X", (), {"co_varnames": ()})()).co_varnames:
        return
    original_init = Retry.__init__

    def patched_init(self, *args, **kwargs):
        if "method_whitelist" in kwargs:
            kwargs["allowed_methods"] = kwargs.pop("method_whitelist")
        return original_init(self, *args, **kwargs)

    patched_init._qf_patched = True  # type: ignore[attr-defined]
    Retry.__init__ = patched_init  # type: ignore[method-assign]


_patch_urllib3_retry_for_pytrends()


KEYWORD_BATCHES: list[tuple[str, list[str]]] = [
    ("en_core",   ["buy gold", "gold price", "gold crash", "silver squeeze", "sell gold"]),
    ("en_macro",  ["inflation", "recession", "fed rate", "dollar collapse", "safe haven"]),
    ("eu",        ["acheter or", "cours de l'or", "comprar oro", "goldpreis", "oro"]),
    ("asia",      ["altin fiyati", "sona bhav", "emas hari ini", "gia vang", "giá vàng"]),
]

REGIONS = ["", "US", "IN", "TR", "VN", "RU", "DE", "FR", "HK", "CA", "AU"]


class GoogleTrendsConnector(BaseConnector):
    meta = ConnectorMeta(
        name="google_trends",
        category="sentiment",
        frequency="weekly",
        requires_key=False,
        description="Google Trends — retail attention on gold (multi-region, multi-keyword)",
    )

    TIMEFRAME = "today 5-y"  # last 5 years weekly

    def _trendreq(self):
        from pytrends.request import TrendReq
        return TrendReq(hl="en-US", tz=0, retries=2, backoff_factor=0.5, timeout=(5, 30))

    def _fetch_batch(self, pytrends, keywords: list[str], geo: str) -> pd.DataFrame:
        pytrends.build_payload(kw_list=keywords, geo=geo, timeframe=self.TIMEFRAME)
        df = pytrends.interest_over_time()
        if df is None or df.empty:
            return pd.DataFrame()
        if "isPartial" in df.columns:
            df = df.drop(columns=["isPartial"])
        df = df.reset_index().rename(columns={"date": "date"})
        return df

    def fetch(self) -> pd.DataFrame:
        from loguru import logger
        try:
            pytrends = self._trendreq()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[google_trends] init failed: {e}")
            return pd.DataFrame()

        rows: list[dict] = []
        for region in REGIONS:
            for batch_name, kws in KEYWORD_BATCHES:
                try:
                    df = self._fetch_batch(pytrends, kws, region)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[google_trends] {batch_name}/{region or 'GLOBAL'}: {e}")
                    time.sleep(2)
                    continue
                if df.empty:
                    continue
                for kw in kws:
                    if kw not in df.columns:
                        continue
                    slug = (
                        kw.lower().replace(" ", "_").replace("'", "")
                        .replace("é", "e").replace("à", "a").replace("ı", "i")
                    )
                    region_slug = region.lower() or "global"
                    for _, r in df.iterrows():
                        try:
                            val = float(r[kw])
                        except (ValueError, TypeError):
                            continue
                        rows.append({
                            "date": r["date"],
                            "metric": f"gtrends_{region_slug}_{slug}",
                            "value": val,
                            "unit": "gt_index",
                            "region": region or "GLOBAL",
                            "keyword": kw,
                        })
                time.sleep(1.5)  # avoid rate limit
        return pd.DataFrame(rows)
