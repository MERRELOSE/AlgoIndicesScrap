#!/usr/bin/env python3
"""
Massive MT5 extractor for forex.

Uses mt5.copy_rates_range() in time-sliced chunks so we can get far beyond the
5000-bar terminal limit. Saves to parquet with duplicate & gap checks.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from loguru import logger


TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

# Approximate minutes per timeframe — used to size chunks
TF_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440,
}


def _ensure_mt5() -> None:
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")


def _rates_to_df(rates) -> pd.DataFrame:
    df = pd.DataFrame(rates)
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("datetime")
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close",
        "tick_volume": "TickVolume", "real_volume": "RealVolume", "spread": "Spread",
    })
    keep = [c for c in ["Open", "High", "Low", "Close", "TickVolume", "Spread"] if c in df.columns]
    return df[keep].sort_index()


def extract_symbol(
    symbol: str,
    timeframe: str,
    years: float = 3.0,
    chunk_days: int = 30,
    out_dir: str | Path = "forex/data/raw",
    overwrite: bool = False,
) -> Optional[pd.DataFrame]:
    """
    Extract OHLCV for a forex symbol over `years` years, chunk by chunk.

    Returns the concatenated DataFrame (UTC index) or None on failure.
    """
    tf = TIMEFRAME_MAP.get(timeframe)
    if tf is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / f"{symbol}_{timeframe}.parquet"

    requested_start = datetime.utcnow() - timedelta(days=int(365.25 * years))
    if cache.exists() and not overwrite:
        df_cached = pd.read_parquet(cache)
        cached_start = df_cached.index.min().to_pydatetime().replace(tzinfo=None)
        # Accept cache if it starts at or before the requested start (with 7-day tolerance)
        if cached_start <= requested_start + timedelta(days=7):
            logger.info(f"[{symbol} {timeframe}] cache hit: {len(df_cached)} bars "
                        f"(from {df_cached.index.min().date()})")
            return df_cached
        else:
            logger.info(f"[{symbol} {timeframe}] cache only goes to {cached_start.date()}, "
                        f"need {requested_start.date()} — extending...")

    _ensure_mt5()
    if not mt5.symbol_select(symbol, True):
        logger.error(f"[{symbol}] symbol_select failed: {mt5.last_error()}")
        return None

    end = datetime.utcnow()
    start = end - timedelta(days=int(365.25 * years))

    chunks: list[pd.DataFrame] = []
    cur_end = end
    expected_bars_per_chunk = (chunk_days * 1440) / TF_MINUTES[timeframe]
    logger.info(
        f"[{symbol} {timeframe}] extracting {years}y in {chunk_days}d chunks "
        f"(~{expected_bars_per_chunk:.0f} bars/chunk)"
    )

    while cur_end > start:
        cur_start = max(cur_end - timedelta(days=chunk_days), start)
        rates = mt5.copy_rates_range(symbol, tf, cur_start, cur_end)
        if rates is None or len(rates) == 0:
            logger.warning(f"  empty chunk {cur_start.date()} -> {cur_end.date()}")
        else:
            chunks.append(_rates_to_df(rates))
        cur_end = cur_start - timedelta(seconds=1)

    if not chunks:
        logger.error(f"[{symbol} {timeframe}] no data extracted")
        return None

    df = pd.concat(chunks).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df = df[(df.index >= pd.Timestamp(start, tz="UTC")) & (df.index <= pd.Timestamp(end, tz="UTC"))]

    # Quality report
    span_days = (df.index[-1] - df.index[0]).days
    expected_total = (span_days * 1440) / TF_MINUTES[timeframe]
    completeness = len(df) / expected_total if expected_total > 0 else 0
    logger.info(
        f"[{symbol} {timeframe}] {len(df)} bars | "
        f"{df.index[0].date()} -> {df.index[-1].date()} | "
        f"completeness ~{completeness:.1%} (forex closes weekends, <1.0 expected)"
    )

    df.to_parquet(cache, compression="snappy")
    logger.info(f"  saved {cache}")
    return df


def extract_multi_timeframe(
    symbol: str,
    timeframes: list[str],
    years: float = 3.0,
    out_dir: str | Path = "forex/data/raw",
    overwrite: bool = False,
) -> dict[str, pd.DataFrame]:
    """Extract several timeframes for the same symbol."""
    result: dict[str, pd.DataFrame] = {}
    for tf in timeframes:
        df = extract_symbol(symbol, tf, years=years, out_dir=out_dir, overwrite=overwrite)
        if df is not None:
            result[tf] = df
    return result


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Forex massive extractor")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframes", nargs="+", default=["M15", "H1", "H4"])
    parser.add_argument("--years", type=float, default=3.0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{level: <7}</level> {message}")

    extract_multi_timeframe(args.symbol, args.timeframes, years=args.years, overwrite=args.overwrite)
    mt5.shutdown()


if __name__ == "__main__":
    main()
