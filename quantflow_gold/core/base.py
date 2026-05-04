"""Base class for all connectors. Enforces a common contract."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger

from quantflow_gold.core.schema import CANONICAL_COLUMNS
from quantflow_gold.storage.parquet_writer import write_parquet

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PACKAGE_ROOT.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data"


@dataclass
class ConnectorMeta:
    name: str
    category: str  # macro, positioning, flows, physical, mining, price, sentiment
    frequency: str  # daily, weekly, monthly, event
    requires_key: bool = False
    description: str = ""


class BaseConnector(ABC):
    """All connectors inherit from this. Contract:
      - fetch() returns a pandas DataFrame in canonical long format
        (date, value, metric, unit, source, ingested_at, [extra columns])
      - run() calls fetch() and writes Parquet to data/processed/<name>/
    """

    meta: ConnectorMeta

    def __init__(self, data_dir: Optional[str] = None):
        env_dir = os.getenv("DATA_DIR")
        if data_dir is not None:
            base = Path(data_dir)
        elif env_dir:
            base = Path(env_dir)
        else:
            base = DEFAULT_DATA_DIR
        self.data_dir = base.expanduser().resolve()
        self.out_dir = self.data_dir / "processed" / self.meta.name
        self.raw_dir = self.data_dir / "raw" / self.meta.name
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def fetch(self, **kwargs) -> pd.DataFrame:
        """Fetch data and return in canonical long format."""

    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure canonical columns exist. Missing optional cols get filled."""
        for col in CANONICAL_COLUMNS:
            if col not in df.columns:
                if col == "source":
                    df[col] = self.meta.name
                elif col == "ingested_at":
                    df[col] = datetime.now(timezone.utc)
                else:
                    df[col] = None
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=False)
            df = df.dropna(subset=["date"])
        return df

    def run(self, **kwargs) -> Path:
        logger.info(f"[{self.meta.name}] fetching...")
        df = self.fetch(**kwargs)
        df = self.validate(df)
        out = write_parquet(df, self.out_dir, self.meta.name)
        try:
            display = out.relative_to(REPO_ROOT)
        except ValueError:
            display = out
        logger.success(f"[{self.meta.name}] wrote {len(df):,} rows -> {display}")
        return out
