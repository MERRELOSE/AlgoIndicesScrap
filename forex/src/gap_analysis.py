#!/usr/bin/env python3
"""
Weekend gap analysis for Deriv MT5 forex / metals / indices.

Approach: pull D1 data, detect weekend boundaries (>=1.9 day gap between two
consecutive daily candles = weekend), then measure:
  - gap size distribution (absolute % and signed)
  - Friday-direction continuation vs fade ratio
  - naive strategy PnL (bet Friday direction, close at next open)
  - oracle edge (upper bound = always correct direction)

The oracle edge is what a perfect ML classifier could capture.
The naive edge is what a dumb "follow Friday" rule gets.
Reality lives between the two.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from forex.src.extractor import extract_symbol


def extract_weekend_gaps(df_d1: pd.DataFrame) -> pd.DataFrame:
    """
    From D1 OHLC data, extract one row per weekend gap.

    A weekend gap = transition between a candle whose timestamp is >=1.9 days
    after the previous candle. This catches Fri->Mon reliably, ignores
    intra-week holidays (1-day gaps).

    Returned columns:
      friday_*       : the last trading day before the weekend
      next_open      : first open after the weekend (this candle's Open)
      next_close     : close of that first post-weekend day
      gap_abs        : next_open - friday_close (price units)
      gap_pct        : gap relative to friday_close (%)
      gap_days       : calendar gap between the two candles
      friday_direction / gap_direction : sign(body)
      is_continuation / is_fade : relation between the two signs
    """
    df = df_d1.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df = df.sort_index()

    prev = df.shift(1)
    gap_days = (df.index.to_series() - df.index.to_series().shift(1)).dt.total_seconds() / 86400.0

    weekend_mask = gap_days >= 1.9
    weekend_mask = weekend_mask.fillna(False)

    gaps = pd.DataFrame(index=df.index[weekend_mask])
    gaps["friday_open"] = prev["Open"].loc[gaps.index]
    gaps["friday_high"] = prev["High"].loc[gaps.index]
    gaps["friday_low"] = prev["Low"].loc[gaps.index]
    gaps["friday_close"] = prev["Close"].loc[gaps.index]
    gaps["next_open"] = df["Open"].loc[gaps.index]
    gaps["next_high"] = df["High"].loc[gaps.index]
    gaps["next_low"] = df["Low"].loc[gaps.index]
    gaps["next_close"] = df["Close"].loc[gaps.index]
    gaps["gap_days"] = gap_days.loc[gaps.index]

    gaps["gap_abs"] = gaps["next_open"] - gaps["friday_close"]
    gaps["gap_pct"] = gaps["gap_abs"] / gaps["friday_close"] * 100.0

    gaps["friday_body_pct"] = (gaps["friday_close"] - gaps["friday_open"]) / gaps["friday_open"] * 100.0
    gaps["friday_range_pct"] = (gaps["friday_high"] - gaps["friday_low"]) / gaps["friday_open"] * 100.0
    gaps["next_range_pct"] = (gaps["next_high"] - gaps["next_low"]) / gaps["next_open"] * 100.0

    gaps["friday_direction"] = np.sign(gaps["friday_body_pct"])
    gaps["gap_direction"] = np.sign(gaps["gap_pct"])
    nonzero = gaps["gap_direction"] != 0
    gaps["is_continuation"] = (gaps["friday_direction"] == gaps["gap_direction"]) & nonzero
    gaps["is_fade"] = (gaps["friday_direction"] == -gaps["gap_direction"]) & nonzero

    return gaps.dropna(subset=["gap_pct", "friday_body_pct"])


def summarize_gaps(gaps: pd.DataFrame, symbol: str, sig_threshold_pct: float = 0.15) -> dict:
    """
    Headline stats for one symbol.

    sig_threshold_pct: gap considered "exploitable" if abs(gap) exceeds this.
    0.15% is roughly 15 pips on EURUSD, ~20 pips on USDJPY, ~$5 on gold at 3400.
    """
    if gaps.empty:
        return {}

    abs_gap = gaps["gap_pct"].abs()

    # Naive strategies (no model)
    pnl_cont = gaps["friday_direction"] * gaps["gap_pct"]    # bet Friday direction
    pnl_fade = -gaps["friday_direction"] * gaps["gap_pct"]   # bet opposite

    # Oracle: always know direction -> capture full abs(gap)
    oracle_pnl = abs_gap

    sig_mask = abs_gap >= sig_threshold_pct

    def _sharpe(series: pd.Series) -> float:
        s = series.std()
        return float(series.mean() / s * np.sqrt(52)) if s > 0 else 0.0

    stats = {
        "symbol": symbol,
        "n_weekends": int(len(gaps)),
        "gap_abs_pct_mean": float(abs_gap.mean()),
        "gap_abs_pct_median": float(abs_gap.median()),
        "gap_abs_pct_std": float(abs_gap.std()),
        "gap_abs_pct_p75": float(abs_gap.quantile(0.75)),
        "gap_abs_pct_p90": float(abs_gap.quantile(0.90)),
        "gap_abs_pct_p95": float(abs_gap.quantile(0.95)),
        "gap_pct_mean_signed": float(gaps["gap_pct"].mean()),
        "pct_significant": float(sig_mask.mean() * 100.0),
        "pct_continuation": float(gaps["is_continuation"].mean() * 100.0),
        "pct_fade": float(gaps["is_fade"].mean() * 100.0),
        "pnl_cont_mean_pct": float(pnl_cont.mean()),
        "pnl_cont_win_rate_pct": float((pnl_cont > 0).mean() * 100.0),
        "pnl_cont_sharpe": _sharpe(pnl_cont),
        "pnl_fade_mean_pct": float(pnl_fade.mean()),
        "pnl_fade_win_rate_pct": float((pnl_fade > 0).mean() * 100.0),
        "pnl_fade_sharpe": _sharpe(pnl_fade),
        "oracle_edge_pct": float(oracle_pnl.mean()),
    }
    stats["best_naive"] = "continuation" if stats["pnl_cont_mean_pct"] > stats["pnl_fade_mean_pct"] else "fade"
    stats["best_naive_edge_pct"] = max(stats["pnl_cont_mean_pct"], stats["pnl_fade_mean_pct"])
    stats["bias_strength"] = abs(stats["pct_continuation"] - 50.0)  # >0 means skew in one direction
    return stats


def analyze_symbol(
    symbol: str,
    years: float = 5.0,
    sig_threshold_pct: float = 0.15,
    out_dir: str = "forex/data/raw",
    gaps_dir: str = "forex/data/gaps",
) -> Optional[dict]:
    """Extract D1 data, detect weekend gaps, return summary stats dict or None."""
    df = extract_symbol(symbol, "D1", years=years, out_dir=out_dir)
    if df is None or len(df) < 100:
        logger.warning(f"[{symbol}] insufficient D1 data")
        return None
    gaps = extract_weekend_gaps(df)
    if gaps.empty or len(gaps) < 20:
        logger.warning(f"[{symbol}] only {len(gaps)} weekend gaps - skipping")
        return None
    stats = summarize_gaps(gaps, symbol, sig_threshold_pct=sig_threshold_pct)
    # Persist gap detail for later model training
    gp = Path(gaps_dir)
    gp.mkdir(parents=True, exist_ok=True)
    gaps.to_parquet(gp / f"{symbol}_weekend_gaps.parquet")
    logger.info(
        f"[{symbol}] n={stats['n_weekends']} | |gap|={stats['gap_abs_pct_mean']:.3f}% "
        f"(p90={stats['gap_abs_pct_p90']:.3f}%) | cont={stats['pct_continuation']:.1f}% | "
        f"oracle={stats['oracle_edge_pct']:.4f}% | best_naive={stats['best_naive']}"
        f"({stats['best_naive_edge_pct']:+.4f}%)"
    )
    return stats
