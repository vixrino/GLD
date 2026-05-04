"""Shared helpers."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential


def env(name: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    v = os.getenv(name, default)
    if required and not v:
        raise RuntimeError(f"Missing required env var {name}")
    return v


def http_get(
    url: str,
    *,
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: float = 30.0,
    retries: int = 3,
) -> httpx.Response:
    """Robust GET with bounded retries and default UA.

    `retries=1` disables exponential backoff (single attempt) — useful for
    fan-out connectors (e.g. USGS, Wikipedia) where a single failure should
    not freeze the run for hours.
    """
    h = {
        "User-Agent": headers.get("User-Agent") if headers and "User-Agent" in headers
        else "QuantFlow-Gold/0.1 (data collection)"
    }
    if headers:
        h.update(headers)

    @retry(stop=stop_after_attempt(retries), wait=wait_exponential(min=1, max=8))
    def _do():
        r = httpx.get(url, headers=h, params=params, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        return r

    return _do()


def download_to(url: str, dest: Path, *, headers: Optional[dict] = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, headers=headers or {}, timeout=60.0, follow_redirects=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    return dest


def now_utc():
    return datetime.now(timezone.utc)
