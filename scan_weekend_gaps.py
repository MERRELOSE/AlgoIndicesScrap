#!/usr/bin/env python3
"""
Weekend gap exploitability scan over a broad Deriv MT5 universe.

Ranks each symbol by:
  - oracle_edge_pct : what a perfect direction predictor could capture per weekend
  - best_naive_edge : what a dumb "follow Friday" or "fade Friday" rule gets
  - pct_significant : how often the gap is >= threshold (tradeability)
  - bias_strength   : how far continuation-rate is from 50/50 (exploitable bias)

The winners of this scan become the target list for model training.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import MetaTrader5 as mt5
from loguru import logger

from forex.src.gap_analysis import analyze_symbol


# ---------------------------------------------------------------------------
# Universe: Deriv MT5 standard names. Micro/alt variants omitted to avoid dupes.
# ---------------------------------------------------------------------------
UNIVERSE = [
    # Forex majors
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
    # Forex crosses (JPY)
    "EURJPY", "GBPJPY", "AUDJPY", "CADJPY", "CHFJPY", "NZDJPY", "SGDJPY", "HKDJPY",
    # Forex crosses (non-JPY)
    "EURGBP", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
    "GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD",
    "AUDCAD", "AUDCHF", "AUDNZD", "AUDSGD",
    "NZDCAD", "NZDCHF", "NZDSGD",
    "CADCHF",
    # Exotic (usually gap hard on weekends)
    "USDZAR", "USDMXN", "USDPLN", "USDSEK", "USDNOK", "USDSGD", "USDHKD",
    "EURMXN", "EURNOK", "EURPLN", "EURSEK", "EURSGD", "EURHKD", "EURZAR",
    "GBPNOK", "GBPSEK", "GBPSGD",
    # Metals
    "XAUUSD", "XAGUSD", "XAUEUR", "XAGEUR",
]


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{level: <7}</level> {message}")

    years = 5.0
    logger.info(f"Scanning {len(UNIVERSE)} symbols with {years}y of D1 history...")

    results: list[dict] = []
    failures: list[str] = []
    for sym in UNIVERSE:
        try:
            stats = analyze_symbol(sym, years=years)
            if stats:
                results.append(stats)
            else:
                failures.append(sym)
        except Exception as e:
            logger.error(f"[{sym}] error: {e}")
            failures.append(sym)

    mt5.shutdown()

    if not results:
        logger.error("No results - aborting")
        return

    df = pd.DataFrame(results)
    # Sort by oracle edge (theoretical ceiling for ML approach)
    df = df.sort_values("oracle_edge_pct", ascending=False).reset_index(drop=True)

    out_dir = Path("forex/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "weekend_gap_ranking.csv"
    df.to_csv(out_csv, index=False)

    display_cols = [
        "symbol", "n_weekends",
        "gap_abs_pct_mean", "gap_abs_pct_p90", "pct_significant",
        "pct_continuation", "bias_strength",
        "pnl_cont_mean_pct", "pnl_fade_mean_pct", "best_naive", "best_naive_edge_pct",
        "oracle_edge_pct",
    ]
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 220)
    pd.set_option("display.float_format", lambda x: f"{x:.4f}")

    logger.info("\n" + "=" * 90)
    logger.info("TOP 15 BY ORACLE EDGE (theoretical ceiling if model predicts direction)")
    logger.info("=" * 90)
    print(df[display_cols].head(15).to_string(index=False))

    logger.info("\n" + "=" * 90)
    logger.info("TOP 10 BY NAIVE EDGE (Friday-follow or Friday-fade, no model)")
    logger.info("=" * 90)
    df_naive = df.sort_values("best_naive_edge_pct", ascending=False).head(10)
    print(df_naive[display_cols].to_string(index=False))

    logger.info("\n" + "=" * 90)
    logger.info("TOP 10 BY BIAS STRENGTH (skew from 50/50 cont/fade - most predictable)")
    logger.info("=" * 90)
    df_bias = df.sort_values("bias_strength", ascending=False).head(10)
    print(df_bias[display_cols].to_string(index=False))

    logger.info(f"\n-> Full ranking saved to {out_csv}")
    if failures:
        logger.warning(f"Skipped/failed ({len(failures)}): {', '.join(failures)}")


if __name__ == "__main__":
    main()
