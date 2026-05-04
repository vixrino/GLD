"""Open-Meteo Archive — historical weather at major gold-mining sites.

Archive API (free, no auth):
    https://archive-api.open-meteo.com/v1/archive
Daily variables we pull:
    temperature_2m_max, temperature_2m_min, temperature_2m_mean
    precipitation_sum, snowfall_sum, windspeed_10m_max

Sites chosen for systemic gold supply:
    Carlin (Nevada, US)         41.017, -116.12
    Witwatersrand (ZA)         -26.17,  28.04
    Kalgoorlie (WA)            -30.75, 121.47
    Yanacocha (Peru)            -6.98, -78.50
    Obuasi (Ghana)               6.20,  -1.67
    Lihir (PNG)                 -3.10, 152.62
    Muruntau (Uzbekistan)       41.52,  64.56
    Kumtor (Kyrgyzstan)         41.87,  78.20
    Porgera (PNG)               -5.47, 143.15
    Timmins (Ontario, CA)       48.47, -81.33
    Red Lake (Ontario, CA)      51.03, -93.82

Why: Heavy rains / blizzards / heatwaves routinely cause quarterly production
misses. Correlating weather deviations w/ miner 10-Q tone is a neat signal.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from quantflow_gold.core.base import BaseConnector, ConnectorMeta
from quantflow_gold.core.utils import http_get


SITES = {
    "carlin_nv":       (41.017, -116.12),
    "witwatersrand":   (-26.17,   28.04),
    "kalgoorlie":      (-30.75,  121.47),
    "yanacocha_pe":    (-6.98,  -78.50),
    "obuasi_gh":       (6.20,    -1.67),
    "lihir_png":       (-3.10,  152.62),
    "muruntau_uz":     (41.52,   64.56),
    "kumtor_kg":       (41.87,   78.20),
    "porgera_png":     (-5.47,  143.15),
    "timmins_ca":      (48.47,  -81.33),
    "red_lake_ca":     (51.03,  -93.82),
    "oyu_tolgoi_mn":   (43.00,  107.00),
    "grasberg_id":     (-4.05,  137.12),
}

DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "precipitation_sum",
    "snowfall_sum",
    "windspeed_10m_max",
]


class OpenMeteoConnector(BaseConnector):
    meta = ConnectorMeta(
        name="open_meteo",
        category="alt",
        frequency="daily",
        requires_key=False,
        description="Weather archive at major gold-mining sites (supply disruption proxy)",
    )

    BASE = "https://archive-api.open-meteo.com/v1/archive"

    def _fetch_site(self, lat: float, lon: float, start: date, end: date) -> dict:
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": ",".join(DAILY_VARS),
            "timezone": "UTC",
        }
        r = http_get(self.BASE, params=params, timeout=30.0, retries=2)
        return r.json()

    def fetch(self, days_back: int = 365 * 5) -> pd.DataFrame:
        from loguru import logger
        end_d = date.today() - timedelta(days=2)  # archive lags ~24-48h
        start_d = end_d - timedelta(days=days_back)

        rows: list[dict] = []
        for site, (lat, lon) in SITES.items():
            try:
                data = self._fetch_site(lat, lon, start_d, end_d)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[open_meteo] {site} failed: {e}")
                continue
            daily = data.get("daily", {})
            dates = daily.get("time", [])
            if not dates:
                continue
            for var in DAILY_VARS:
                series = daily.get(var, [])
                for dt_str, val in zip(dates, series):
                    if val is None:
                        continue
                    rows.append({
                        "date": dt_str,
                        "metric": f"weather_{site}_{var}",
                        "value": float(val),
                        "unit": "degC" if "temperature" in var else ("mm" if "precip" in var or "snow" in var else "m/s"),
                        "site": site,
                        "lat": lat,
                        "lon": lon,
                    })
        return pd.DataFrame(rows)
