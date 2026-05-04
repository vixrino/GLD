"""CLI entry point for all QuantFlow-Gold connectors.

Usage:
    python -m quantflow_gold.run --list
    python -m quantflow_gold.run --source fred
    python -m quantflow_gold.run --source cftc_cot
    python -m quantflow_gold.run --all
    python -m quantflow_gold.run --all --skip-keys          # skip those needing API keys
    python -m quantflow_gold.run --all --only-no-key        # same as above
    python -m quantflow_gold.run --source yahoo --start 2000-01-01

Output:
    data/processed/<source>/latest.parquet           # rolling up-to-date
    data/processed/<source>/snapshots/<ts>.parquet   # historical snapshots
    data/raw/<source>/...                            # original artefacts (XLS/PDF/JSON)
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from typing import Type

import click
from dotenv import load_dotenv
from loguru import logger

from quantflow_gold.core.base import BaseConnector, REPO_ROOT  # noqa: F401

from quantflow_gold.connectors.macro.fred import FredConnector
from quantflow_gold.connectors.macro.treasury_tga import TreasuryTgaConnector
from quantflow_gold.connectors.positioning.cftc_cot import CftcCotConnector
from quantflow_gold.connectors.flows.etf_holdings import EtfHoldingsConnector
from quantflow_gold.connectors.physical.perth_mint import PerthMintConnector
from quantflow_gold.connectors.physical.sge import SgeConnector
from quantflow_gold.connectors.physical.central_bank_gold import CentralBankGoldConnector
from quantflow_gold.connectors.price.yahoo import YahooConnector
from quantflow_gold.connectors.price.historical_long import HistoricalLongConnector
from quantflow_gold.connectors.sentiment.google_trends import GoogleTrendsConnector
from quantflow_gold.connectors.sentiment.gdelt import GdeltConnector
from quantflow_gold.connectors.sentiment.wikipedia import WikipediaPageviewsConnector
from quantflow_gold.connectors.sentiment.stocktwits import StocktwitsConnector
from quantflow_gold.connectors.sentiment.mining_news import MiningNewsConnector
from quantflow_gold.connectors.mining.sec_edgar import SecEdgarConnector
from quantflow_gold.connectors.mining.miners_yahoo import MinersYahooConnector
from quantflow_gold.connectors.alt.usgs_earthquakes import UsgsEarthquakesConnector
from quantflow_gold.connectors.alt.open_meteo import OpenMeteoConnector
from quantflow_gold.connectors.alt.defillama import DefiLlamaConnector
from quantflow_gold.connectors.alt.binance_gold import BinanceGoldConnector
from quantflow_gold.connectors.alt.coingecko_gold import CoinGeckoGoldConnector


REGISTRY: dict[str, Type[BaseConnector]] = {
    # --- Price (run yahoo early so miners_yahoo can read it) ---
    "yahoo":              YahooConnector,
    "historical_long":    HistoricalLongConnector,
    # --- Macro ---
    "fred":               FredConnector,
    "treasury_tga":       TreasuryTgaConnector,
    # --- Positioning ---
    "cftc_cot":           CftcCotConnector,
    # --- Flows ---
    "etf_holdings":       EtfHoldingsConnector,
    # --- Physical ---
    "perth_mint":         PerthMintConnector,
    "sge":                SgeConnector,
    "central_bank_gold":  CentralBankGoldConnector,
    # --- Mining ---
    "sec_edgar":          SecEdgarConnector,
    # --- Sentiment ---
    "google_trends":      GoogleTrendsConnector,
    "gdelt":              GdeltConnector,
    "wikipedia":          WikipediaPageviewsConnector,
    "stocktwits":         StocktwitsConnector,
    "mining_news":        MiningNewsConnector,
    # --- Alt ---
    "usgs_earthquakes":   UsgsEarthquakesConnector,
    "open_meteo":         OpenMeteoConnector,
    "defillama":          DefiLlamaConnector,
    "binance_gold":       BinanceGoldConnector,
    "coingecko_gold":     CoinGeckoGoldConnector,
    # --- Derived (runs last, depends on yahoo) ---
    "miners_yahoo":       MinersYahooConnector,
}


KEY_ENV: dict[str, list[str]] = {
    "fred": ["FRED_API_KEY"],
}


def _has_keys(source: str) -> bool:
    reqs = KEY_ENV.get(source, [])
    return all(os.getenv(k) for k in reqs)


def _run_one(source: str, **kwargs) -> bool:
    cls = REGISTRY.get(source)
    if cls is None:
        logger.error(f"unknown source: {source}")
        return False
    if cls.meta.requires_key and not _has_keys(source):
        missing = [k for k in KEY_ENV.get(source, []) if not os.getenv(k)]
        logger.warning(f"[{source}] missing env {missing}, skipping")
        return False
    t0 = time.time()
    try:
        conn = cls()
        conn.run(**kwargs)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[{source}] FAILED: {e}")
        logger.debug(traceback.format_exc())
        return False
    dt = time.time() - t0
    logger.info(f"[{source}] done in {dt:.1f}s")
    return True


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--source", "-s", multiple=True, help="Connector id. Repeatable.")
@click.option("--all", "run_all", is_flag=True, help="Run every connector.")
@click.option("--list", "list_sources", is_flag=True, help="List available connectors.")
@click.option("--skip-keys", is_flag=True, help="Skip connectors requiring API keys if keys missing (default behaviour).")
@click.option("--only-no-key", is_flag=True, help="Run only connectors that do not require API keys.")
@click.option("--start", default=None, help="Optional start date (YYYY-MM-DD) for connectors that accept it.")
@click.option("--data-dir", default=None, help="Override DATA_DIR.")
@click.option("--quiet", is_flag=True)
def main(source, run_all, list_sources, skip_keys, only_no_key, start, data_dir, quiet):
    load_dotenv(REPO_ROOT / ".env")
    load_dotenv()

    if data_dir:
        os.environ["DATA_DIR"] = data_dir

    log_level = "WARNING" if quiet else os.getenv("LOG_LEVEL", "INFO")
    logger.remove()
    logger.add(sys.stderr, level=log_level, format="<green>{time:HH:mm:ss}</green> <lvl>{level: <8}</lvl> {message}")

    if list_sources:
        click.echo("Available connectors:\n")
        for sid, cls in REGISTRY.items():
            key = " (KEY)" if cls.meta.requires_key else ""
            click.echo(f"  {sid:<22} {cls.meta.category:<12} {cls.meta.frequency:<10} {cls.meta.description}{key}")
        return

    if not source and not run_all:
        click.echo("Nothing to do. Pass --source <id>, --all or --list.", err=True)
        sys.exit(2)

    sources = list(source) if source else list(REGISTRY.keys())

    if only_no_key:
        sources = [s for s in sources if not REGISTRY[s].meta.requires_key]

    kwargs = {}
    if start:
        kwargs["start"] = start

    ok = 0
    ko = 0
    for s in sources:
        if _run_one(s, **kwargs):
            ok += 1
        else:
            ko += 1

    logger.info(f"--- summary: ok={ok} ko={ko} total={ok+ko} ---")
    sys.exit(0 if ko == 0 else 1)


if __name__ == "__main__":
    main()
