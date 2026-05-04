"""Gold-related news headlines from open RSS feeds + VADER sentiment.

Why this is a useful free signal:
- Headlines move retail flow into ETFs (GLD/IAU) within minutes.
- Mining.com tracks every junior + major producer announcement (production
  cuts, mergers, accidents) — a leading indicator for sector basket beta.
- Goldswitzerland publishes Swiss-bullion-bank commentary (closed shop) —
  unusual and contrarian view.

Feeds used (200 OK, no key, public RSS):
- https://www.mining.com/feed/                       (high-volume mining news)
- https://goldswitzerland.com/feed/                   (gold-centric commentary)

We:
- Parse RSS via stdlib `xml.etree.ElementTree` (avoids extra deps).
- Filter items whose title/description contain gold-related keywords.
- Score titles with VADER (already used by stocktwits / gdelt).

Output (long format, one row per metric per item):
- date, metric=news_title_polarity, value=compound score, unit=score
- date, metric=news_published_count, value=1, unit=count
- date, metric=news_keyword_<kw>_count, ...

We also persist the raw items (per-feed) into `data/raw/mining_news/...` so
quants can re-score with a different model later.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import http_get, now_utc


FEEDS: dict[str, str] = {
    "mining_com":         "https://www.mining.com/feed/",
    "goldswitzerland":    "https://goldswitzerland.com/feed/",
}

# Case-insensitive substring filters. Items must match at least one to be kept.
GOLD_KEYWORDS = [
    "gold", "bullion", "xau", "comex", "lbma", "central bank reserves",
    "newmont", "barrick", "agnico", "kinross", "gdx", "gld", "iau",
    "miner", "mine ", "smelter", "refinery", "ounce",
]

NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc":      "http://purl.org/dc/elements/1.1/",
}


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _parse_pubdate(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s)
    except Exception:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None


class MiningNewsConnector(BaseConnector):
    meta = ConnectorMeta(
        name="mining_news",
        category="sentiment",
        frequency="daily",
        requires_key=False,
        description="Gold-related news headlines (mining.com, goldswitzerland) + VADER",
    )

    def _fetch_feed(self, name: str, url: str) -> list[dict]:
        from loguru import logger
        try:
            r = http_get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; QuantFlow-Gold/0.1)",
                    "Accept": "application/rss+xml,application/xml,text/xml,*/*",
                },
                timeout=20.0,
                retries=2,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[mining_news] {name} fetch failed: {e}")
            return []

        try:
            root = ET.fromstring(r.text)
        except ET.ParseError as e:
            logger.warning(f"[mining_news] {name} XML parse failed: {e}")
            return []

        items: list[dict] = []
        # RSS 2.0: <rss><channel><item>... ; Atom: <feed><entry>...
        for item in root.iter():
            tag = item.tag.lower().split("}")[-1]
            if tag not in ("item", "entry"):
                continue

            def text(child_tag: str) -> str:
                child = item.find(child_tag)
                if child is None:
                    return ""
                return _strip_html(child.text or "")

            title = text("title") or text("{http://www.w3.org/2005/Atom}title")
            description = (
                text("description")
                or text("{http://www.w3.org/2005/Atom}summary")
                or _strip_html(item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or "")
            )
            pub_raw = (
                item.findtext("pubDate")
                or item.findtext("{http://www.w3.org/2005/Atom}published")
                or item.findtext("{http://www.w3.org/2005/Atom}updated")
                or item.findtext("{http://purl.org/dc/elements/1.1/}date")
                or ""
            )
            link = item.findtext("link") or ""

            published = _parse_pubdate(pub_raw)
            items.append({
                "feed": name,
                "title": title,
                "description": description[:500],
                "link": link,
                "published": published.isoformat() if published else None,
            })
        return items

    def fetch(self) -> pd.DataFrame:
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        except ImportError as e:
            from loguru import logger
            logger.error(f"[mining_news] vaderSentiment missing: {e}")
            return pd.DataFrame()

        analyzer = SentimentIntensityAnalyzer()
        kws = [kw.lower() for kw in GOLD_KEYWORDS]

        all_items: list[dict] = []
        for name, url in FEEDS.items():
            items = self._fetch_feed(name, url)
            kept = []
            for it in items:
                blob = f"{it['title']} {it['description']}".lower()
                if not any(kw in blob for kw in kws):
                    continue
                kept.append(it)
            all_items.extend(kept)

        # Persist raw payload for reproducibility
        raw_path: Path = self.raw_dir / f"mining_news_{now_utc():%Y-%m-%dT%H%M%S}.json"
        raw_path.write_text(json.dumps(all_items, ensure_ascii=False, indent=2))

        if not all_items:
            return pd.DataFrame()

        rows: list[dict] = []
        for it in all_items:
            scores = analyzer.polarity_scores(it["title"] or "")
            pub = it.get("published")
            try:
                date = pd.to_datetime(pub, utc=True).tz_convert(None) if pub else now_utc().replace(tzinfo=None)
            except Exception:
                date = now_utc().replace(tzinfo=None)

            rows.append({"date": date, "metric": f"news_{it['feed']}_polarity",   "value": scores["compound"], "unit": "score", "feed": it["feed"], "title": it["title"][:200]})
            rows.append({"date": date, "metric": f"news_{it['feed']}_pos",         "value": scores["pos"],     "unit": "score", "feed": it["feed"]})
            rows.append({"date": date, "metric": f"news_{it['feed']}_neg",         "value": scores["neg"],     "unit": "score", "feed": it["feed"]})
            rows.append({"date": date, "metric": f"news_{it['feed']}_neu",         "value": scores["neu"],     "unit": "score", "feed": it["feed"]})
            rows.append({"date": date, "metric": f"news_{it['feed']}_count",       "value": 1.0,                "unit": "count", "feed": it["feed"]})

            blob = f"{it['title']} {it['description']}".lower()
            for kw in kws:
                if kw in blob:
                    rows.append({"date": date, "metric": f"news_kw_{kw.strip().replace(' ', '_')}_count", "value": 1.0, "unit": "count", "feed": it["feed"]})

        return pd.DataFrame(rows)
