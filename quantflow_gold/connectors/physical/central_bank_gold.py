"""Central bank gold reserves.

Strategy (two sources, best-effort):

1) Primary — World Gold Council XLSX (monthly updated). The exact URL changes
   with every release, so we HEAD-probe a few candidate filenames; if none
   returns an actual XLSX, we silently skip and fall back to Wikipedia.

2) Fallback — Wikipedia "Gold reserve" article hosts an auto-updated
   ranking table mirroring the WGC / IMF IFS data. Parsed with
   ``pandas.read_html``.

Both give us per-country gold tonnes held by central banks / sovereign funds.

Output (canonical long-format):
    cb_gold_tonnes_<country_slug>      (one row per country, latest snapshot)
    cb_gold_world_total_tonnes         (derived)
    cb_gold_top10_share_pct            (derived)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
from loguru import logger

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import download_to, http_get


WGC_CANDIDATE_URLS = [
    "https://www.gold.org/download/file/5121/World_Official_Gold_Holdings_as_of_Dec2023_IFS.xlsx",
    "https://www.gold.org/download/file/5021/World_Official_Gold_Holdings_IFS.xlsx",
    "https://www.gold.org/sites/default/files/market-data/Central%20banks%20and%20other%20institutions.xlsx",
]

WIKI_URL = "https://en.wikipedia.org/wiki/Gold_reserve"

_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _to_slug(s: str) -> str:
    s = re.sub(r"\[[^\]]*\]", "", s)
    out = "".join(c if c.isalnum() else "_" for c in s.lower()).strip("_")
    return re.sub(r"_+", "_", out)


def _parse_num(token: str) -> float | None:
    token = re.sub(r"\[[^\]]*\]", "", str(token))
    m = _NUM_RE.search(token.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


class CentralBankGoldConnector(BaseConnector):
    meta = ConnectorMeta(
        name="central_bank_gold",
        category="physical",
        frequency="monthly",
        requires_key=False,
        description="Official central bank gold reserves per country (WGC/IMF IFS + Wikipedia fallback)",
    )

    def _from_wgc(self) -> pd.DataFrame:
        raw_path: Path | None = None
        for url in WGC_CANDIDATE_URLS:
            try:
                candidate = self.raw_dir / f"wgc_cb_holdings_{datetime.now(timezone.utc):%Y-%m-%d}.xlsx"
                download_to(url, candidate)
                with open(candidate, "rb") as f:
                    head = f.read(4)
                if head[:2] != b"PK":
                    logger.debug(f"[central_bank_gold] WGC {url}: not a real xlsx (got {head!r}), skip")
                    candidate.unlink(missing_ok=True)
                    continue
                raw_path = candidate
                break
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[central_bank_gold] WGC {url}: {e}")
                raw_path = None
        if not raw_path or not raw_path.exists():
            return pd.DataFrame()
        try:
            xls = pd.read_excel(raw_path, sheet_name=None, header=None)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[central_bank_gold] WGC parse failed: {e}")
            return pd.DataFrame()

        rows: list[dict] = []
        snapshot_date = datetime.now(timezone.utc).date()
        for sheet_name, df in xls.items():
            flat = df.astype(str).apply(lambda s: "|".join(x for x in s if x and x != "nan"), axis=1)
            for _, raw_line in flat.items():
                parts = [p.strip() for p in raw_line.split("|") if p.strip()]
                if len(parts) < 2:
                    continue
                country = parts[0]
                for token in parts[1:]:
                    val = _parse_num(token)
                    if val is None:
                        continue
                    if 0 < val < 10000:
                        slug = _to_slug(country)
                        if not slug or slug == "total" or len(slug) > 40:
                            continue
                        rows.append({
                            "date": snapshot_date,
                            "metric": f"cb_gold_tonnes_{slug}",
                            "value": val,
                            "unit": "tonnes",
                            "country": country,
                            "source_detail": f"wgc_sheet_{sheet_name}",
                        })
                        break
        return pd.DataFrame(rows)

    def _from_wikipedia(self) -> pd.DataFrame:
        try:
            r = http_get(WIKI_URL)
            tables = pd.read_html(StringIO(r.text))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[central_bank_gold] wikipedia fetch/parse failed: {e}")
            return pd.DataFrame()

        target: pd.DataFrame | None = None
        country_col = tonnes_col = None
        for t in tables:
            cols = [str(c) for c in t.columns]
            cols_lower = [c.lower() for c in cols]
            cc = next((c for c, cl in zip(cols, cols_lower) if "country" in cl or "organization" in cl), None)
            tc = next(
                (c for c, cl in zip(cols, cols_lower)
                 if ("metric ton" in cl) or ("tonne" in cl) or ("gold holdings" in cl) or ("holdings" in cl and "gold" in cl)),
                None,
            )
            if cc and tc and len(t) > 10:
                target = t
                country_col, tonnes_col = cc, tc
                break

        if target is None:
            logger.warning("[central_bank_gold] wikipedia: no matching ranking table found")
            return pd.DataFrame()

        snapshot_date = datetime.now(timezone.utc).date()
        rows: list[dict] = []
        for _, row in target.iterrows():
            country = re.sub(r"\s+", " ", str(row[country_col])).strip()
            val = _parse_num(row[tonnes_col])
            if val is None or val <= 0:
                continue
            slug = _to_slug(country)
            if not slug or any(stop in slug for stop in ("world", "total", "euro_area", "imf", "european_central")):
                continue
            if len(slug) > 40:
                continue
            rows.append({
                "date": snapshot_date,
                "metric": f"cb_gold_tonnes_{slug}",
                "value": val,
                "unit": "tonnes",
                "country": country,
                "source_detail": "wikipedia",
            })
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.drop_duplicates(subset=["metric"], keep="first").reset_index(drop=True)
        return df

    def fetch(self) -> pd.DataFrame:
        df = self._from_wgc()
        if df.empty:
            df = self._from_wikipedia()
        if df.empty:
            return df

        tonnes = df[df["unit"] == "tonnes"]
        if not tonnes.empty:
            total = float(tonnes["value"].sum())
            top10 = float(tonnes.nlargest(10, "value")["value"].sum())
            snap = tonnes["date"].iloc[0]
            extra = pd.DataFrame([
                {"date": snap, "metric": "cb_gold_world_total_tonnes", "value": total, "unit": "tonnes"},
                {"date": snap, "metric": "cb_gold_top10_share_pct",    "value": (top10 / total * 100) if total else 0.0, "unit": "pct"},
            ])
            df = pd.concat([df, extra], ignore_index=True)
        logger.info(f"[central_bank_gold] {len(df)} rows ({(df['unit']=='tonnes').sum()} countries)")
        return df
