"""USGS earthquakes — mining-region seismic events (supply-disruption proxy).

USGS FDSN Event API (no auth):
    https://earthquake.usgs.gov/fdsnws/event/1/query

We query M >= 4.5 quakes in bounding boxes around the top gold-producing
regions:
  South Africa (Witwatersrand basin)
  Nevada (Carlin trend) + USA
  Western Australia (Kalgoorlie)
  Peru (Yanacocha, major mining belts)
  Ghana, Burkina Faso (West Africa gold belt)
  Papua New Guinea (Porgera, Lihir)
  Russia (Far East gold mines)
  Indonesia (Grasberg)
  Canada (Abitibi, Yukon)
  Kyrgyzstan (Kumtor)
  Uzbekistan (Muruntau)

Output per day, per region:
  usgs_<region>_quakes_count
  usgs_<region>_max_magnitude
  usgs_<region>_sum_energy_1e13J   (energy ~ 10^(1.5*M + 4.8) J)
"""

from __future__ import annotations

from datetime import date, timedelta
from math import pow as math_pow

import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import http_get


REGIONS = {
    # (min_lat, max_lat, min_lon, max_lon)
    "south_africa":     (-35, -22, 16, 33),
    "nevada_us":        (34, 42, -120, -114),
    "western_australia":(-35, -14, 112, 130),
    "peru":             (-18, 0, -82, -68),
    "west_africa":      (4, 15, -17, 5),
    "png":              (-12, -1, 140, 156),
    "russia_far_east":  (42, 72, 100, 180),
    "indonesia":        (-11, 7, 95, 141),
    "canada_abitibi":   (44, 70, -140, -60),
    "kyrgyzstan":       (39, 44, 69, 80),
    "uzbekistan":       (37, 46, 55, 74),
    "china":            (18, 54, 73, 135),
}


class UsgsEarthquakesConnector(BaseConnector):
    meta = ConnectorMeta(
        name="usgs_earthquakes",
        category="alt",
        frequency="daily",
        requires_key=False,
        description="USGS quakes M>=4.5 in gold-mining regions (disruption proxy)",
    )

    BASE = "https://earthquake.usgs.gov/fdsnws/event/1/query"

    def _fetch_region(self, region: str, bbox, start: date, end: date) -> list[dict]:
        min_lat, max_lat, min_lon, max_lon = bbox
        params = {
            "format": "geojson",
            "starttime": start.isoformat(),
            "endtime": end.isoformat(),
            "minmagnitude": 4.5,
            "minlatitude": min_lat,
            "maxlatitude": max_lat,
            "minlongitude": min_lon,
            "maxlongitude": max_lon,
            "limit": 20000,
        }
        r = http_get(self.BASE, params=params, timeout=45.0, retries=2)
        return r.json().get("features", [])

    def fetch(self, days_back: int = 365 * 5) -> pd.DataFrame:
        from loguru import logger
        end_d = date.today()
        start_d = end_d - timedelta(days=days_back)

        per_day: dict[tuple[str, str], dict] = {}
        seen_ids_per_region: dict[str, set[str]] = {}
        for region, bbox in REGIONS.items():
            try:
                features = self._fetch_region(region, bbox, start_d, end_d)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[usgs] {region} failed: {e}")
                continue
            seen_ids = seen_ids_per_region.setdefault(region, set())
            n_dupes = 0
            for feat in features:
                ev_id = feat.get("id")
                if ev_id is not None:
                    if ev_id in seen_ids:
                        n_dupes += 1
                        continue
                    seen_ids.add(ev_id)
                props = feat.get("properties", {})
                mag = props.get("mag")
                ts_ms = props.get("time")
                if mag is None or ts_ms is None:
                    continue
                if float(mag) < 4.5:
                    continue
                day = pd.Timestamp(ts_ms, unit="ms", tz="UTC").date()
                key = (region, str(day))
                bucket = per_day.setdefault(key, {"count": 0, "max_mag": 0.0, "energy": 0.0})
                bucket["count"] += 1
                bucket["max_mag"] = max(bucket["max_mag"], float(mag))
                try:
                    bucket["energy"] += math_pow(10, 1.5 * float(mag) + 4.8) / 1e13
                except Exception:
                    pass
            if n_dupes:
                logger.debug(f"[usgs] {region}: dedup'd {n_dupes} duplicate event ids")

        rows = []
        for (region, day), b in per_day.items():
            rows.append({"date": day, "metric": f"usgs_{region}_quakes_count",     "value": float(b["count"]),   "unit": "count"})
            rows.append({"date": day, "metric": f"usgs_{region}_max_mag",          "value": b["max_mag"],        "unit": "richter"})
            rows.append({"date": day, "metric": f"usgs_{region}_energy_1e13J",     "value": b["energy"],         "unit": "1e13 J"})
        return pd.DataFrame(rows)
