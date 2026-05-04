"""Wikipedia pageviews — attention metric on gold-related articles.

Endpoint (no auth, no key):
    https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/
    {project}/{access}/{agent}/{article}/{granularity}/{start}/{end}

Where:
    project     = en.wikipedia, fr.wikipedia, tr.wikipedia, etc.
    access      = all-access | desktop | mobile-web | mobile-app
    agent       = user (excluding bots/spiders)
    granularity = daily | monthly
    YYYYMMDD range, e.g. 20180101/20251231

Useful signal because:
  - spikes during gold-standard debates, bank crises, currency devaluations
  - multi-language tracks region-specific attention
  - very clean data (Wikimedia's own telemetry)

Articles we track:
  en: Gold, Gold_as_an_investment, Gold_standard, Fiat_money,
      Hyperinflation, Weimar_Republic, Inflation, Federal_Reserve,
      Gold_reserve, Central_bank, Silver_as_an_investment
  fr: Or, Étalon-or
  de: Goldpreis, Goldstandard
  tr: Altın
  hi: सोना
  zh: 黃金
  ru: Золото
  es: Patrón_oro
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import http_get


PAGES = [
    ("en.wikipedia", "Gold"),
    ("en.wikipedia", "Gold_as_an_investment"),
    ("en.wikipedia", "Gold_standard"),
    ("en.wikipedia", "Fiat_money"),
    ("en.wikipedia", "Hyperinflation"),
    ("en.wikipedia", "Weimar_Republic"),
    ("en.wikipedia", "Inflation"),
    ("en.wikipedia", "Federal_Reserve"),
    ("en.wikipedia", "Gold_reserve"),
    ("en.wikipedia", "Central_bank_gold_reserves"),
    ("en.wikipedia", "Silver_as_an_investment"),
    ("en.wikipedia", "GLD_(exchange-traded_fund)"),
    ("fr.wikipedia", "Or"),
    ("fr.wikipedia", "Étalon-or"),
    ("de.wikipedia", "Goldpreis"),
    ("de.wikipedia", "Goldstandard"),
    ("tr.wikipedia", "Altın"),
    ("hi.wikipedia", "सोना"),
    ("zh.wikipedia", "黃金"),
    ("ru.wikipedia", "Золото"),
    ("es.wikipedia", "Patrón_oro"),
]


class WikipediaPageviewsConnector(BaseConnector):
    meta = ConnectorMeta(
        name="wikipedia",
        category="sentiment",
        frequency="daily",
        requires_key=False,
        description="Wikipedia pageviews per article (multi-lang) — retail attention",
    )

    BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"

    def _fetch_page(self, project: str, article: str, start: date, end: date) -> list[dict]:
        import urllib.parse
        article_enc = urllib.parse.quote(article, safe="")
        url = (
            f"{self.BASE}/{project}/all-access/user/{article_enc}"
            f"/daily/{start:%Y%m%d}/{end:%Y%m%d}"
        )
        r = http_get(url, headers={"User-Agent": "QuantFlow-Gold/0.1 (data collection; contact: ops@example.com)"}, timeout=20.0, retries=2)
        data = r.json().get("items", [])
        return data

    def fetch(self, days_back: int = 365 * 5) -> pd.DataFrame:
        from loguru import logger
        end_d = date.today() - timedelta(days=1)
        start_d = end_d - timedelta(days=days_back)

        rows: list[dict] = []
        for project, article in PAGES:
            try:
                items = self._fetch_page(project, article, start_d, end_d)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[wikipedia] {project}/{article} failed: {e}")
                continue
            slug_lang = project.split(".")[0]
            slug_art = (
                article.lower().replace(" ", "_").replace("(", "").replace(")", "")
                .replace("-", "_").replace("__", "_")
            )
            for it in items:
                ts = it.get("timestamp", "")[:8]  # YYYYMMDD
                try:
                    dt = pd.Timestamp(f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}")
                except Exception:
                    continue
                rows.append({
                    "date": dt,
                    "metric": f"wiki_{slug_lang}_{slug_art}_views",
                    "value": float(it.get("views", 0)),
                    "unit": "views",
                    "project": project,
                    "article": article,
                })
        return pd.DataFrame(rows)
