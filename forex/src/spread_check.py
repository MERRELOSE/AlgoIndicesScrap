#!/usr/bin/env python3
"""
Weekend-open spread audit for a short-list of symbols.

Measures, from M1 OHLCV+Spread data, the actual spread cost incurred when
trading across the weekend:
  - entry_spread   : spread in the last 5 minutes before Friday close
  - open_spread    : spread in the first 5 minutes after Sunday reopen
  - hour1_spread   : median spread during the first hour of the new week

Converts spreads (in points) into % of mid-price so they are directly
comparable to the `oracle_edge_pct` from gap_analysis.

Output per symbol:
  net_edge_optimistic = oracle_edge - median_entry_spread_pct
  net_edge_pessimistic = oracle_edge - median_open_spread_pct

Re-run this on a different broker account (XM/Axi/VTMarket) to compare
which one gives the best net edge for the same strategy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from loguru import logger

from forex.src.extractor import extract_symbol


def _point_size(symbol: str) -> Optional[float]:
    """Lookup MT5 symbol point size (e.g. 0.00001 for EURUSD, 0.01 for XAUUSD).
    Ensures MT5 is initialized and the symbol is selected first."""
    if not mt5.initialize():
        logger.error(f"MT5 initialize failed: {mt5.last_error()}")
        return None
    if not mt5.symbol_select(symbol, True):
        logger.warning(f"[{symbol}] symbol_select failed: {mt5.last_error()}")
        return None
    info = mt5.symbol_info(symbol)
    if info is None:
        return None
    return info.point


def audit_symbol_spread(
    symbol: str,
    months: float = 3.0,
    weekend_gap_min_hours: float = 40.0,
) -> Optional[dict]:
    """
    Extract M1, detect weekend boundaries, collect spread samples.

    Returns a dict with median/p95 spread stats at different points of the
    weekend transition, expressed in both points and % of mid-price.
    """
    point = _point_size(symbol)
    if point is None or point <= 0:
        logger.error(f"[{symbol}] point size unavailable")
        return None

    years = months / 12.0
    df = extract_symbol(symbol, "M1", years=years, out_dir="forex/data/raw", overwrite=False)
    if df is None or len(df) < 5000:
        logger.warning(f"[{symbol}] not enough M1 data ({0 if df is None else len(df)} bars)")
        return None
    if "Spread" not in df.columns:
        logger.warning(f"[{symbol}] no Spread column in M1 - broker does not record it")
        return None

    df = df.sort_index()
    gap_hours = (df.index.to_series() - df.index.to_series().shift(1)).dt.total_seconds() / 3600.0
    weekend_starts = df.index[gap_hours >= weekend_gap_min_hours]  # candle AT the new session start

    entry_spreads: list[float] = []   # last 5 M1 before weekend
    open_spreads: list[float] = []    # first 5 M1 after weekend
    hour1_spreads: list[float] = []   # first 60 M1 after weekend, median
    entry_spreads_pct: list[float] = []
    open_spreads_pct: list[float] = []
    hour1_spreads_pct: list[float] = []

    for t_open in weekend_starts:
        # Previous row in df = last M1 before weekend
        idx_pos = df.index.get_loc(t_open)
        if idx_pos < 5 or idx_pos + 60 >= len(df):
            continue
        pre = df.iloc[idx_pos - 5: idx_pos]
        post5 = df.iloc[idx_pos: idx_pos + 5]
        post60 = df.iloc[idx_pos: idx_pos + 60]

        entry_spreads.append(float(pre["Spread"].median()))
        open_spreads.append(float(post5["Spread"].median()))
        hour1_spreads.append(float(post60["Spread"].median()))

        # mid-price approximations for %
        pre_mid = float(pre["Close"].median())
        open_mid = float(post5["Open"].median())
        hour_mid = float(post60["Close"].median())
        if pre_mid > 0:
            entry_spreads_pct.append(pre["Spread"].median() * point / pre_mid * 100.0)
        if open_mid > 0:
            open_spreads_pct.append(post5["Spread"].median() * point / open_mid * 100.0)
        if hour_mid > 0:
            hour1_spreads_pct.append(post60["Spread"].median() * point / hour_mid * 100.0)

    if not open_spreads:
        logger.warning(f"[{symbol}] no valid weekend samples in window")
        return None

    def _stat(arr: list[float]) -> tuple[float, float, float]:
        a = np.asarray(arr, dtype=float)
        return float(np.median(a)), float(np.quantile(a, 0.95)), float(np.max(a))

    e_med, e_p95, e_max = _stat(entry_spreads)
    o_med, o_p95, o_max = _stat(open_spreads)
    h_med, h_p95, h_max = _stat(hour1_spreads)
    e_med_pct = float(np.median(entry_spreads_pct))
    o_med_pct = float(np.median(open_spreads_pct))
    o_p95_pct = float(np.quantile(open_spreads_pct, 0.95))
    h_med_pct = float(np.median(hour1_spreads_pct))

    return {
        "symbol": symbol,
        "n_weekends_sampled": len(open_spreads),
        "entry_spread_pts_med": e_med, "entry_spread_pts_p95": e_p95,
        "open_spread_pts_med": o_med, "open_spread_pts_p95": o_p95, "open_spread_pts_max": o_max,
        "hour1_spread_pts_med": h_med, "hour1_spread_pts_p95": h_p95,
        "entry_spread_pct_med": e_med_pct,
        "open_spread_pct_med": o_med_pct,
        "open_spread_pct_p95": o_p95_pct,
        "hour1_spread_pct_med": h_med_pct,
        "spread_widen_ratio": float(o_med / e_med) if e_med > 0 else np.nan,
    }


def merge_with_ranking(
    spread_rows: list[dict],
    ranking_csv: str = "forex/reports/weekend_gap_ranking.csv",
) -> pd.DataFrame:
    """
    Merge spread audit with the gap ranking and compute net edge.

    Round-trip cost model:
      - Long weekend: entry at Friday ask (cost = entry spread/2 vs mid),
                       exit at Sunday bid (cost = open spread/2 vs mid)
      - Short: mirror
    Round-trip cost (vs mid-to-mid) ≈ (entry_spread + open_spread) / 2 in pct.
    We use the full sum as a conservative estimate.
    """
    if not spread_rows:
        return pd.DataFrame()
    sp = pd.DataFrame(spread_rows)
    rk = pd.read_csv(ranking_csv)
    merged = sp.merge(rk[["symbol", "oracle_edge_pct", "pct_significant",
                          "pct_continuation", "bias_strength", "n_weekends"]],
                      on="symbol", how="left")

    # Optimistic: only entry spread (exit at Sunday bid assumed fair)
    merged["net_edge_optimistic_pct"] = merged["oracle_edge_pct"] - merged["entry_spread_pct_med"]
    # Realistic: entry + half of Sunday widening
    merged["net_edge_realistic_pct"] = (
        merged["oracle_edge_pct"] - (merged["entry_spread_pct_med"] + merged["open_spread_pct_med"]) / 2.0
    )
    # Pessimistic: full Sunday spread (worst case)
    merged["net_edge_pessimistic_pct"] = merged["oracle_edge_pct"] - merged["open_spread_pct_med"]

    def _verdict(row) -> str:
        if row["net_edge_realistic_pct"] <= 0:
            return "REJECT"
        if row["net_edge_realistic_pct"] < 0.05:
            return "MARGINAL"
        if row["spread_widen_ratio"] > 4:
            return "RISKY (weekend widens >4x)"
        return "OK"

    merged["verdict"] = merged.apply(_verdict, axis=1)
    merged = merged.sort_values("net_edge_realistic_pct", ascending=False).reset_index(drop=True)
    return merged
