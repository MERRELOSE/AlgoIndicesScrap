#!/usr/bin/env python3
"""
Behavioral analysis pipeline.

For a given pair + timeframe:
 1. Extract data (H4 context too)
 2. Define big-move events (R:R target, horizon)
 3. Build context features, bin them
 4. Discover single-feature signals on train half
 5. Combine significant singles into pairs (lift + stat validation)
 6. Validate out-of-sample on test half
 7. Report: top long recipes, top short recipes, profitability proxy

Also includes a `--scalping` mode that runs the same pipeline on M5/M15 with
tighter target/horizon suited to short-horizon trading.

Usage:
    python forex/run_behavior.py --pair EURUSD --timeframe H1 --years 5
    python forex/run_behavior.py --pair EURUSD --timeframe M15 --years 2 --scalping
    python forex/run_behavior.py --pair EURUSD --timeframe M5  --years 1 --scalping
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forex.src.extractor import extract_symbol   # noqa: E402
from forex.src.features import atr               # noqa: E402
from forex.src.behavior.events import EventConfig, detect_big_moves, base_rates  # noqa: E402
from forex.src.behavior.context import build_context, discretize               # noqa: E402
from forex.src.behavior.recipes import (                                       # noqa: E402
    discover_single_signals, discover_combos,
    validate_out_of_sample, recipes_to_df,
)

warnings.filterwarnings("ignore")


# ============================================================
# Config presets
# ============================================================
def preset(tf: str, scalping: bool) -> EventConfig:
    """Pick sensible target/horizon per timeframe."""
    if scalping:
        if tf == "M5":
            return EventConfig(target_atr=2.0, stop_atr=1.0, horizon=24)   # 2h fwd
        if tf == "M15":
            return EventConfig(target_atr=2.0, stop_atr=1.0, horizon=16)   # 4h fwd
    # Swing / position - 2R target gives enough events for discovery
    if tf == "H4":
        return EventConfig(target_atr=2.0, stop_atr=1.0, horizon=24)       # 4 days
    if tf == "H1":
        return EventConfig(target_atr=2.0, stop_atr=1.0, horizon=24)       # 1 day
    if tf == "M15":
        return EventConfig(target_atr=2.0, stop_atr=1.0, horizon=32)       # 8h
    if tf == "M5":
        return EventConfig(target_atr=1.5, stop_atr=1.0, horizon=36)       # 3h
    return EventConfig()


# ============================================================
# Pipeline
# ============================================================
def run(pair: str, timeframe: str, years: float, overwrite: bool, scalping: bool,
        min_lift: float, top_k: int) -> None:
    logger.info(f"{'='*78}\n  BEHAVIORAL ANALYSIS: {pair} {timeframe} ({years}y) "
                f"{'[SCALPING]' if scalping else '[SWING]'}\n{'='*78}")

    # ---- Data ----
    out_dir = ROOT / "forex" / "data" / "raw"
    df = extract_symbol(pair, timeframe, years=years, out_dir=out_dir, overwrite=overwrite)
    htf = None
    try:
        htf = extract_symbol(pair, "H4", years=years, out_dir=out_dir, overwrite=False)
    except Exception:
        pass
    mt5.shutdown()

    if df is None or len(df) < 2000:
        logger.error("Not enough data.")
        return

    df["atr_14"] = atr(df["High"], df["Low"], df["Close"], 14)
    logger.info(f"  data: {len(df)} bars  | {df.index[0].date()} → {df.index[-1].date()}")

    # ---- Events ----
    cfg = preset(timeframe, scalping)
    logger.info(f"  event config: target={cfg.target_atr}×ATR  stop={cfg.stop_atr}×ATR  "
                f"horizon={cfg.horizon} bars")
    events = detect_big_moves(df, cfg)
    rates = base_rates(events)
    logger.info(f"  base rates: long_tp={rates['long']:.2%}  short_tp={rates['short']:.2%}  "
                f"any_big_move={rates['any_big_move']:.2%}  (N={rates['n']:,})")

    # ---- Context ----
    htf_close = htf["Close"] if htf is not None else None
    ctx = build_context(df, htf_close=htf_close)
    bins = discretize(ctx, n_bins=4)
    logger.info(f"  context matrix: {bins.shape}  ({bins.shape[1]} binned columns)")

    # ---- Train / test split (time-based 70/30) ----
    split = int(0.7 * len(bins))
    train_idx = bins.index[:split]
    test_idx  = bins.index[split:]
    bins_train = bins.loc[train_idx]
    bins_test  = bins.loc[test_idx]

    # Align events on the same indices
    events_long_train = events["event_long"].loc[train_idx].dropna()
    events_short_train = events["event_short"].loc[train_idx].dropna()
    events_long_test = events["event_long"].loc[test_idx].dropna()
    events_short_test = events["event_short"].loc[test_idx].dropna()

    # ---- Discover: singles then pairs ----
    for side in ["long", "short"]:
        logger.info(f"\n  -- Discovery [{side.upper()}] --")
        ev_tr = events_long_train if side == "long" else events_short_train
        ev_te = events_long_test if side == "long" else events_short_test

        # Seeds = loose (lift >= 1.02) so pairs/triples have material to combine;
        # final filter (singles/pairs/triples kept) = strict (>= min_lift).
        seeds = discover_single_signals(
            bins_train, ev_tr, direction=side,
            min_n=80, p_max=0.10, min_lift=1.02,
        )
        singles = [r for r in seeds if r.lift >= min_lift and r.p_value <= 0.05]
        logger.info(f"    singles: {len(seeds)} seed candidates | {len(singles)} with lift ≥ {min_lift}")
        if seeds:
            logger.info(f"    best singles: " + " | ".join(
                f"{r.features[0]} lift={r.lift:.2f} n={r.n}" for r in seeds[:5]))

        pairs = discover_combos(
            bins_train, ev_tr, direction=side, seeds=seeds,
            combo_size=2, min_n=50, p_max=0.05, min_lift=min_lift,
        )
        logger.info(f"    pairs:   {len(pairs)}")

        triples = discover_combos(
            bins_train, ev_tr, direction=side, seeds=seeds,
            combo_size=3, min_n=30, p_max=0.05, min_lift=min_lift + 0.05,
        )
        logger.info(f"    triples: {len(triples)}")

        all_recipes = singles + pairs + triples
        all_recipes.sort(key=lambda r: r.lift, reverse=True)

        # Out-of-sample validation
        oos = validate_out_of_sample(all_recipes, bins_test, ev_te, min_n=20)
        # Pair in-sample and out-of-sample for reporting
        oos_map = {r.features: r for r in oos}

        report_rows = []
        for r in all_recipes[: top_k * 3]:
            o = oos_map.get(r.features)
            report_rows.append({
                "size": len(r.features),
                "recipe": r.label(),
                "n_IS": r.n,
                "rate_IS": r.event_rate,
                "lift_IS": r.lift,
                "p_IS": r.p_value,
                "n_OOS": o.n if o else 0,
                "rate_OOS": o.event_rate if o else np.nan,
                "lift_OOS": o.lift if o else np.nan,
                "valid_OOS": o.is_valid if o else False,
            })
        report_df = pd.DataFrame(report_rows)

        # Keep only those with OOS lift confirming and lift_OOS >= 1.1
        if report_df.empty or "valid_OOS" not in report_df.columns:
            valid_robust = pd.DataFrame()
        else:
            valid_robust = report_df[
                (report_df["valid_OOS"] == True)
                & (report_df["lift_OOS"] >= 1.1)
            ].sort_values("lift_OOS", ascending=False).head(top_k)

        print(f"\n  [{side.upper()}] TOP {top_k} ROBUST RECIPES (in-sample + out-of-sample)")
        if valid_robust.empty:
            print("    (no recipe survives OOS validation)")
        else:
            print(valid_robust.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

        # Save full report
        reports_dir = ROOT / "forex" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        tag = "scalp" if scalping else "swing"
        path = reports_dir / f"behavior_{pair}_{timeframe}_{side}_{tag}_{ts}.csv"
        report_df.to_csv(path, index=False)
        logger.info(f"    saved -> {path.name}")

    # ---- Scalping profitability estimate (if scalping mode) ----
    if scalping:
        print(f"\n{'='*78}\n  SCALPING PROFITABILITY ESTIMATE ({pair} {timeframe})\n{'='*78}")
        # Assumptions: spread 1.5 pips, slippage 0.3 pips (forex majors)
        spread_pips = 1.5 if "JPY" not in pair and "XAU" not in pair else 2.5
        pip_size = 0.01 if "JPY" in pair else (0.1 if "XAU" in pair else 0.0001)
        # Typical ATR in pips
        atr_pips = (df["atr_14"].dropna().median() / pip_size)
        tp_pips = cfg.target_atr * atr_pips
        sl_pips = cfg.stop_atr * atr_pips
        rr_realized = (tp_pips - spread_pips) / (sl_pips + spread_pips)
        # breakeven WR with this realized R:R
        breakeven_wr = 1.0 / (1.0 + rr_realized) if rr_realized > 0 else 1.0
        print(f"  Typical ATR:       {atr_pips:.1f} pips")
        print(f"  TP barrier:        {tp_pips:.1f} pips  | SL: {sl_pips:.1f} pips")
        print(f"  Spread cost:       {spread_pips:.1f} pips per round trip")
        print(f"  Realized R:R:      {rr_realized:.2f}")
        print(f"  Breakeven WR:      {breakeven_wr:.1%}")
        print(f"  Base rate long:    {rates['long']:.1%}")
        print(f"  Base rate short:   {rates['short']:.1%}")
        if rates['long'] > breakeven_wr or rates['short'] > breakeven_wr:
            print(f"  [OK] Base rates suggest scalping *could* be profitable with the right recipe filter.")
        else:
            lift_needed = breakeven_wr / max(rates['long'], rates['short'])
            print(f"  [WARN] Need recipes with lift >= {lift_needed:.2f} to cross breakeven.")


# ============================================================
# CLI
# ============================================================
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", default="EURUSD")
    parser.add_argument("--timeframe", default="H1")
    parser.add_argument("--years", type=float, default=5.0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--scalping", action="store_true", help="Tuned for M5/M15 scalping targets")
    parser.add_argument("--min-lift", type=float, default=1.15)
    parser.add_argument("--top-k", type=int, default=15)
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{level: <7}</level> {message}")

    run(args.pair, args.timeframe, args.years, args.overwrite, args.scalping,
        args.min_lift, args.top_k)


if __name__ == "__main__":
    main()
