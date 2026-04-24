#!/usr/bin/env python3
"""
Weekend spread audit runner.

Usage:
  python check_weekend_spreads.py                    # default broker=deriv, default shortlist
  python check_weekend_spreads.py --broker xm         # tag output as xm
  python check_weekend_spreads.py --symbols AAA BBB   # custom list

Rerun on each broker account (Deriv, XM, Axi, VTMarket...) after switching
MT5 login — the output CSV is tagged per broker so you can diff them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import MetaTrader5 as mt5
from loguru import logger

from forex.src.spread_check import audit_symbol_spread, merge_with_ranking


# Short-list from gap_ranking (Deriv names — may need mapping for other brokers)
DEFAULT_SHORTLIST = [
    # Metals — priority 1 (continuation bias + reasonable spreads expected)
    "XAGUSD", "XAGEUR", "XAUUSD",
    # JPY crosses — priority 2 (fade bias, liquid)
    "AUDJPY", "NZDJPY",
    # Scandi / exotics — priority 3 (big gaps BUT high spread risk)
    "GBPNOK", "USDNOK", "EURNOK", "USDSEK", "GBPSEK", "EURSEK",
    # ZAR
    "USDZAR", "EURZAR",
]


def main() -> None:
    ap = argparse.ArgumentParser(description="Weekend spread audit")
    ap.add_argument("--broker", default="deriv", help="tag used in output filename")
    ap.add_argument("--months", type=float, default=3.0, help="months of M1 history to analyze")
    ap.add_argument("--symbols", nargs="+", default=None, help="override the default shortlist")
    args = ap.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{level: <7}</level> {message}")

    symbols = args.symbols or DEFAULT_SHORTLIST
    logger.info(f"Auditing {len(symbols)} symbols | broker={args.broker} | history={args.months}mo M1")

    rows = []
    for sym in symbols:
        try:
            row = audit_symbol_spread(sym, months=args.months)
            if row:
                rows.append(row)
                logger.info(
                    f"[{sym}] n={row['n_weekends_sampled']} | "
                    f"entry_spread={row['entry_spread_pct_med']:.4f}% | "
                    f"open_spread={row['open_spread_pct_med']:.4f}% "
                    f"(p95={row['open_spread_pct_p95']:.4f}%) | "
                    f"widen_ratio={row['spread_widen_ratio']:.1f}x"
                )
        except Exception as e:
            logger.error(f"[{sym}] audit failed: {e}")

    mt5.shutdown()

    if not rows:
        logger.error("No audit rows — aborting")
        return

    merged = merge_with_ranking(rows)
    if merged.empty:
        logger.error("Merge with ranking failed — check forex/reports/weekend_gap_ranking.csv exists")
        return

    out_dir = Path("forex/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / f"weekend_spread_{args.broker}.csv"
    merged.to_csv(out_csv, index=False)

    display_cols = [
        "symbol", "oracle_edge_pct",
        "entry_spread_pct_med", "open_spread_pct_med", "open_spread_pct_p95",
        "spread_widen_ratio",
        "net_edge_optimistic_pct", "net_edge_realistic_pct", "net_edge_pessimistic_pct",
        "verdict",
    ]
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 220)
    pd.set_option("display.float_format", lambda x: f"{x:.4f}")

    logger.info("\n" + "=" * 100)
    logger.info(f"WEEKEND SPREAD AUDIT — broker={args.broker}")
    logger.info("=" * 100)
    print(merged[display_cols].to_string(index=False))

    survivors = merged[merged["verdict"].isin(["OK", "RISKY (weekend widens >4x)"])]
    if not survivors.empty:
        logger.info("\n-> SURVIVORS (net edge > 0.05% realistic):")
        print(survivors[["symbol", "oracle_edge_pct", "net_edge_realistic_pct", "verdict"]].to_string(index=False))
    rejected = merged[merged["verdict"] == "REJECT"]
    if not rejected.empty:
        logger.warning(f"\n-> REJECTED ({len(rejected)}): " +
                       ", ".join(rejected["symbol"].tolist()))

    logger.info(f"\n-> Full audit saved to {out_csv}")


if __name__ == "__main__":
    main()
