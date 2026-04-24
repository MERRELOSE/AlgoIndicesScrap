#!/usr/bin/env python3
"""
Feature engineering for weekend-gap ML model.

For each historical weekend, builds a feature vector measured AT Friday close
(the moment an EA would decide to enter). Target = sign(gap_pct).

Feature families:
  1. Friday-session dynamics (from H1 bars of the last 24h)
       h24_return, h24_range, h1_last_return, h1_last_range,
       ema_slope_h1, rsi_h1, atr_h1_pct
  2. Weekly context (D1 bars)
       week_return, week_range, dist_from_5d_high/low, body_ratio
  3. Volatility regime (rolling vs 60d baseline)
       atr_pct_percentile, realized_vol_pct_percentile
  4. Cross-asset (metals only)
       gold_silver_ratio, ratio_momentum, gold_vs_dxy_proxy
  5. Temporal
       week_of_month, month, quarter, is_eom_friday,
       prev_weekend_gap_pct, prev_weekend_gap_abs_pct

Target: `y = sign(gap_pct)` (binary -1/+1). Rows with |gap_pct| below a
noise threshold are dropped (not tradable).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from forex.src.extractor import extract_symbol


# ---------------------------------------------------------------------------
# Indicator primitives (kept tiny - no external deps)
# ---------------------------------------------------------------------------

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0).rolling(period).mean()
    down = (-delta.clip(upper=0)).rolling(period).mean()
    rs = up / down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift()).abs(),
        (df["Low"] - df["Close"].shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _pctile_rolling(series: pd.Series, window: int) -> pd.Series:
    """Rolling percentile rank of the last value within the window."""
    return series.rolling(window).apply(
        lambda x: (x.iloc[-1] >= x).mean() if len(x) == window else np.nan,
        raw=False,
    )


# ---------------------------------------------------------------------------
# Per-symbol feature build
# ---------------------------------------------------------------------------

def build_features_for_symbol(
    symbol: str,
    years: float = 5.0,
    min_abs_gap_pct: float = 0.10,
) -> Optional[pd.DataFrame]:
    """
    Build one feature-row per historical weekend for `symbol`.

    Returns DataFrame indexed by the first post-weekend timestamp, with
    feature columns + ['gap_pct', 'y'] (y in {-1, +1}).
    Returns None if data is unavailable.
    """
    df_h1 = extract_symbol(symbol, "H1", years=years)
    df_d1 = extract_symbol(symbol, "D1", years=years)
    if df_h1 is None or df_d1 is None or len(df_h1) < 200 or len(df_d1) < 60:
        logger.warning(f"[{symbol}] insufficient multi-TF data")
        return None

    # Standardize tz
    for d in (df_h1, df_d1):
        if d.index.tz is None:
            d.index = d.index.tz_localize("UTC")

    df_h1 = df_h1.sort_index()
    df_d1 = df_d1.sort_index()

    # --- Identify weekend boundaries in H1 (gap >= 40h between consecutive bars) ---
    gap_hours = (df_h1.index.to_series() - df_h1.index.to_series().shift(1)).dt.total_seconds() / 3600.0
    weekend_starts = df_h1.index[(gap_hours >= 40.0).fillna(False)]

    # --- Pre-compute H1 indicators ---
    df_h1["rsi14"] = _rsi(df_h1["Close"], 14)
    df_h1["atr14"] = _atr(df_h1, 14)
    df_h1["ret1"]  = df_h1["Close"].pct_change() * 100.0
    df_h1["range_pct"] = (df_h1["High"] - df_h1["Low"]) / df_h1["Open"] * 100.0
    df_h1["ema20"] = df_h1["Close"].ewm(span=20, adjust=False).mean()
    df_h1["ema20_slope"] = df_h1["ema20"].diff(5) / df_h1["ema20"].shift(5) * 100.0

    # --- Pre-compute D1 indicators ---
    df_d1["ret1_d"] = df_d1["Close"].pct_change() * 100.0
    df_d1["atr14_d"] = _atr(df_d1, 14)
    df_d1["atr_pct"] = df_d1["atr14_d"] / df_d1["Close"] * 100.0
    df_d1["atr_pctile60"] = _pctile_rolling(df_d1["atr_pct"], 60)
    df_d1["body_pct"] = (df_d1["Close"] - df_d1["Open"]) / df_d1["Open"] * 100.0
    df_d1["range_pct"] = (df_d1["High"] - df_d1["Low"]) / df_d1["Open"] * 100.0
    df_d1["high_5d"] = df_d1["High"].rolling(5).max()
    df_d1["low_5d"]  = df_d1["Low"].rolling(5).min()
    df_d1["week_ret"] = df_d1["Close"].pct_change(5) * 100.0

    rows: list[dict] = []
    for t_open in weekend_starts:
        try:
            # Find Friday close = H1 bar just before this weekend
            pos = df_h1.index.get_loc(t_open)
        except KeyError:
            continue
        if pos < 50: continue
        friday_close_idx = pos - 1
        fc_bar = df_h1.iloc[friday_close_idx]
        fc_time = df_h1.index[friday_close_idx]

        # Last 24 H1 bars of Friday session (up to and including Friday close)
        h24 = df_h1.iloc[friday_close_idx - 23: friday_close_idx + 1]
        if len(h24) < 20: continue

        h24_return = (h24["Close"].iloc[-1] - h24["Open"].iloc[0]) / h24["Open"].iloc[0] * 100.0
        h24_range = (h24["High"].max() - h24["Low"].min()) / h24["Open"].iloc[0] * 100.0

        h1_last_return = fc_bar["ret1"]
        h1_last_range  = fc_bar["range_pct"]
        rsi_h1         = fc_bar["rsi14"]
        atr_h1_pct     = fc_bar["atr14"] / fc_bar["Close"] * 100.0
        ema_slope_h1   = fc_bar["ema20_slope"]

        # Last D1 bar at or before Friday close
        d1_candidates = df_d1.index[df_d1.index <= fc_time]
        if len(d1_candidates) < 30: continue
        last_d1 = df_d1.loc[d1_candidates[-1]]

        week_return = last_d1["week_ret"]
        week_range  = last_d1["range_pct"]
        body_ratio  = (last_d1["body_pct"] / last_d1["range_pct"]) if last_d1["range_pct"] > 0 else 0.0
        dist_high5d = (last_d1["Close"] - last_d1["high_5d"]) / last_d1["high_5d"] * 100.0
        dist_low5d  = (last_d1["Close"] - last_d1["low_5d"]) / last_d1["low_5d"] * 100.0
        atr_pctile  = last_d1["atr_pctile60"]

        # Post-weekend gap (what we want to predict)
        open_after = df_h1.iloc[pos]["Open"]
        gap_pct = (open_after - fc_bar["Close"]) / fc_bar["Close"] * 100.0
        if pd.isna(gap_pct) or abs(gap_pct) < min_abs_gap_pct:
            continue

        # Temporal
        dt = fc_time
        week_of_month = int((dt.day - 1) // 7 + 1)
        month = int(dt.month)
        quarter = int((month - 1) // 3 + 1)
        is_eom = int(week_of_month >= 4)

        rows.append({
            "time_friday_close": fc_time,
            "time_sunday_open": t_open,
            "symbol": symbol,
            # Friday dynamics
            "h24_return": float(h24_return),
            "h24_range": float(h24_range),
            "h1_last_return": float(h1_last_return),
            "h1_last_range": float(h1_last_range),
            "rsi_h1": float(rsi_h1),
            "atr_h1_pct": float(atr_h1_pct),
            "ema_slope_h1": float(ema_slope_h1),
            # Weekly context
            "week_return": float(week_return),
            "week_range": float(week_range),
            "body_ratio": float(body_ratio),
            "dist_high5d_pct": float(dist_high5d),
            "dist_low5d_pct": float(dist_low5d),
            "atr_pctile60": float(atr_pctile) if not pd.isna(atr_pctile) else np.nan,
            # Temporal
            "week_of_month": week_of_month,
            "month": month,
            "quarter": quarter,
            "is_eom_friday": is_eom,
            # Target
            "gap_pct": float(gap_pct),
            "y": int(np.sign(gap_pct)),
        })

    if not rows:
        logger.warning(f"[{symbol}] no valid feature rows")
        return None

    feat = pd.DataFrame(rows).set_index("time_sunday_open").sort_index()
    # Add lagged target: previous weekend's gap (avoid leak by shifting within this symbol)
    feat["prev_gap_pct"] = feat["gap_pct"].shift(1)
    feat["prev_gap_abs_pct"] = feat["gap_pct"].shift(1).abs()

    logger.info(f"[{symbol}] built {len(feat)} feature rows | "
                f"mean |gap|={feat['gap_pct'].abs().mean():.3f}% | "
                f"y_pos_rate={float((feat['y']==1).mean()):.2%}")
    return feat


def build_features_multi(
    symbols: list[str],
    years: float = 5.0,
    out_path: str = "forex/data/gaps/weekend_features.parquet",
) -> Optional[pd.DataFrame]:
    """Run feature builder for several symbols, concatenate, persist."""
    parts = []
    for s in symbols:
        f = build_features_for_symbol(s, years=years)
        if f is not None:
            parts.append(f)
    if not parts:
        return None
    df = pd.concat(parts).sort_index()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out)
    logger.info(f"Saved {len(df)} rows ({len(parts)} symbols) to {out}")
    return df
