"""Parquet writer: one snapshot per run + a rolling `latest.parquet`.

Layout:
    data/processed/<source>/
        snapshots/
            <source>_2025-10-01T22-05-00Z.parquet
        latest.parquet                  # always pointing to most recent complete dataset

Rationale:
- `latest.parquet` is what quants consume.
- snapshots keep full history / audit trail.
- DuckDB can query across snapshots if we need to diff over time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def write_parquet(df: pd.DataFrame, out_dir: Path, source: str) -> Path:
    if df.empty:
        return out_dir / "latest.parquet"

    snapshots = out_dir / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    snap = snapshots / f"{source}_{ts}.parquet"
    df.to_parquet(snap, index=False, compression="zstd")

    latest = out_dir / "latest.parquet"
    df.to_parquet(latest, index=False, compression="zstd")

    return latest
