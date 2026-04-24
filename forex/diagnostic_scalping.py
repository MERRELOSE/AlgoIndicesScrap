#!/usr/bin/env python3
"""
Diagnostic: reproduce what the MT5 EA should have seen on Friday 20-23 UTC bars
over the same backtest period (2025-01 to 2026-04), using the same data.

If Python shows ~50% WR but MT5 shows ~32% WR on the base condition, then either:
  - MQL5 feature computation diverges from Python (bug)
  - OR the Python OOS claim was overfit / lucky

This script computes:
  1. WR of the raw rule "Friday 20-23h UTC long, TP=2*ATR, SL=1*ATR, horizon=16"
     on the exact MT5 backtest window.
  2. WR for each of the 6 Python recipes (MS1-MS6) on the same window.
  3. Sample trades with detailed ATR / BB / EMA50 slope values so we can
     cross-check MQL5.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forex.src.features import atr
from forex.src.behavior.context import build_context, discretize
from forex.src.behavior.events import detect_big_moves, EventConfig


def load_gold_m15():
    p = ROOT / "forex" / "data" / "raw" / "XAUUSD_M15.parquet"
    if not p.exists():
        print(f"Missing {p}. Run `python forex/run_behavior.py --pair XAUUSD --timeframe M15 --years 3 --scalping` first.")
        sys.exit(1)
    df = pd.read_parquet(p)
    return df


def main():
    df = load_gold_m15()
    print(f"Loaded XAUUSD M15: {len(df)} bars from {df.index[0]} to {df.index[-1]}")

    # Same barriers as EA: target=2*ATR, stop=1*ATR, horizon=16
    df["atr_14"] = atr(df["High"], df["Low"], df["Close"], 14)
    cfg = EventConfig(target_atr=2.0, stop_atr=1.0, horizon=16)
    events = detect_big_moves(df, cfg)

    ctx = build_context(df)
    bins = discretize(ctx, n_bins=4)

    # Join everything — bins has atr_14 as a bin label column, df has atr_14 numeric, rename
    bins_r = bins.rename(columns={c: f"bin_{c}" for c in bins.columns})
    full = df.join(events).join(bins_r)

    # Filter to MT5 backtest window: 2025-01-01 to 2026-04-15 (UTC)
    mask = (full.index >= pd.Timestamp("2025-01-01", tz="UTC")) & \
           (full.index <= pd.Timestamp("2026-04-15", tz="UTC"))
    win = full[mask].copy()
    print(f"\nBacktest window subset: {len(win)} bars  from {win.index[0]} to {win.index[-1]}")

    # --- BASE: Friday UTC 20-23 long ---
    fri_mask = (win.index.dayofweek == 4)   # Python convention: Friday = 4
    hour_mask = (win.index.hour >= 20) & (win.index.hour <= 23)
    base = win[fri_mask & hour_mask].dropna(subset=["event_long"])
    wr_base = base["event_long"].mean()
    print(f"\n=== BASE (Friday 20-23 UTC, long 2R/1R in 16 bars) ===")
    print(f"  n = {len(base)} signals | WR = {wr_base:.2%}")
    if len(base) > 0:
        tp = (base['event_long'] == 1).sum()
        sl = (base['event_long'] == 0).sum()
        print(f"  TP hits: {tp} | SL hits: {sl}")

    # --- BASE breakdown by exact hour ---
    print(f"\n=== BASE WR by exact UTC hour ===")
    for h in [20, 21, 22, 23]:
        hb = base[base.index.hour == h]
        if len(hb) < 5: continue
        wr = hb["event_long"].mean()
        tp = (hb["event_long"] == 1).sum()
        sl = (hb["event_long"] == 0).sum()
        print(f"  {h}h UTC: n={len(hb):3d} | WR={wr:.1%} | TP={tp} SL={sl}")

    # --- BASE breakdown by quarter-hour (00, 15, 30, 45) ---
    print(f"\n=== BASE WR by quarter-hour (combined across 20-23h) ===")
    for m in [0, 15, 30, 45]:
        qb = base[base.index.minute == m]
        if len(qb) < 5: continue
        wr = qb["event_long"].mean()
        print(f"  :{m:02d}  n={len(qb):3d} | WR={wr:.1%}")

    # --- Each recipe ---
    recipes = {
        "MS1": lambda r: r.get("bin_ema50_slope", "") == "ema50_slope_q3",
        "MS2": lambda r: r.get("bin_atr_14", "") == "atr_14_q3",
        "MS3": lambda r: r.get("bin_pos_in_range_20", "") == "pos_in_range_20_q4",
        "MS4": lambda r: r.get("bin_sess_ny", "") == "sess_ny_0",
        "MS5": lambda r: r.get("bin_bb_pos", "") == "bb_pos_q4",
        "MS6": lambda r: r.get("bin_atr_14", "") == "atr_14_q2",
    }

    print(f"\n=== RECIPE-LEVEL WR (Friday 20-23 UTC + recipe, by hour) ===")
    for name, cond_fn in recipes.items():
        if len(base) == 0:
            continue
        matches = base.apply(cond_fn, axis=1)
        sub = base[matches]
        if len(sub) < 5:
            print(f"  {name}: n={len(sub)} (too few)")
            continue
        wr = sub["event_long"].mean()
        by_hour = sub.groupby(sub.index.hour)["event_long"].agg(["count", "mean"])
        hour_desc = "  ".join(f"{h}h:n={int(r['count'])}/WR{r['mean']:.0%}" for h, r in by_hour.iterrows())
        print(f"  {name}: n={len(sub):3d}  WR={wr:.1%}  |  {hour_desc}")

    # --- SIMULATE v1.01: 21h UTC Friday + ANY recipe (no base-only) ---
    hr21 = win[(win.index.dayofweek == 4) & (win.index.hour == 21)].dropna(subset=["event_long"])
    print(f"\n=== SIMULATED v1.01 (Friday 21h UTC + any recipe, MAX 1 trade/week) ===")
    print(f"  All Friday 21h bars: n={len(hr21)}")
    hr21_full = hr21.join(bins_r, rsuffix="_b").drop(columns=[c for c in hr21.columns if c.endswith("_b")], errors="ignore")
    hr21_full = hr21
    # re-run recipe matching on hr21
    matches_all_rows = []
    for name, cond_fn in recipes.items():
        matches_all_rows.append(hr21.apply(cond_fn, axis=1).rename(name))
    rmatrix = pd.concat(matches_all_rows, axis=1)
    any_recipe = rmatrix.any(axis=1)
    filt = hr21[any_recipe]
    print(f"  Bars where at least one recipe fires: n={len(filt)}")
    if len(filt) > 0:
        wr = filt["event_long"].mean()
        tp = (filt['event_long'] == 1).sum()
        sl = (filt['event_long'] == 0).sum()
        print(f"  Simulated WR = {wr:.2%} (TP={tp} SL={sl})")

        # MAX 1 PER WEEK: take first bar per calendar week
        filt_weekly = filt.groupby(pd.Grouper(freq="W-FRI")).head(1)
        if len(filt_weekly) > 0:
            wr_w = filt_weekly["event_long"].mean()
            tp_w = (filt_weekly['event_long'] == 1).sum()
            sl_w = (filt_weekly['event_long'] == 0).sum()
            print(f"  MAX 1/week (first matching bar): n={len(filt_weekly)} WR={wr_w:.2%} (TP={tp_w} SL={sl_w})")
            # Expectancy at R:R 2:1
            exp_r = wr_w * 2 - (1 - wr_w) * 1
            print(f"  Expectancy per trade: {exp_r:+.3f} R")

    # --- Sample a few bars for cross-check with MQL5 ---
    print(f"\n=== SAMPLE BARS (first 5 Friday 20-23 UTC signals with pr values) ===")
    if len(base) > 0:
        sample_cols = ["atr_14", "Close"]
        for col in ["atr_14_pr", "bb_width_pr", "bb_pos_pr", "ema50_slope_pr",
                    "rsi_14_pr", "pos_in_range_20_pr"]:
            if col in ctx.columns:
                sample_cols.append(col)
        ctx_sample = ctx.loc[base.index[:5]]
        for col in ["atr_14_pr", "bb_width_pr", "bb_pos_pr", "ema50_slope_pr",
                    "rsi_14_pr", "pos_in_range_20_pr"]:
            if col in ctx.columns:
                ctx_sample = ctx_sample.join(
                    ctx[[col]].rename(columns={col: col + "_copy"}), how="left"
                ) if col + "_copy" not in ctx_sample.columns else ctx_sample

        # Simpler: just print
        for idx in base.index[:5]:
            print(f"\n  {idx}")
            print(f"    Close={df.loc[idx, 'Close']:.2f}  ATR={df.loc[idx, 'atr_14']:.2f}")
            print(f"    event_long={events.loc[idx, 'event_long']}")
            for col in ["atr_14_pr", "bb_width_pr", "bb_pos_pr", "ema50_slope_pr",
                        "rsi_14_pr", "pos_in_range_20_pr"]:
                if col in ctx.columns:
                    print(f"    {col} = {ctx.loc[idx, col]:.3f}")
            for bcol in ["atr_14", "bb_width", "bb_pos", "ema50_slope", "rsi_14",
                         "pos_in_range_20"]:
                if bcol in bins.columns:
                    print(f"    bin[{bcol}] = {bins.loc[idx, bcol]}")


if __name__ == "__main__":
    main()
