#!/usr/bin/env python3
"""
Context feature extraction.

For each bar we compute ~25-30 features that describe the *state of the market
at close of that bar*. These are backward-looking only (no look-ahead).

Features are grouped into discretized levels (low / mid / high / extreme) so
they can be combined into "recipes" downstream.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _safe_pct_rank(s: pd.Series, window: int) -> pd.Series:
    """Rolling percentile rank in [0, 1] — robust to regime shifts."""
    return s.rolling(window, min_periods=window // 2).rank(pct=True)


def build_context(df: pd.DataFrame, htf_close: pd.Series | None = None) -> pd.DataFrame:
    """
    Build a context DataFrame aligned on df.index.

    Columns include (raw) technical indicators plus their rolling percentile
    ranks — the discrete binning in recipes.py works on the percentile columns.
    """
    out = pd.DataFrame(index=df.index)
    close = df["Close"]
    high = df["High"]
    low  = df["Low"]

    # --- Returns & momentum ---
    ret1 = close.pct_change()
    out["ret_1"]  = ret1
    out["ret_5"]  = close.pct_change(5)
    out["ret_20"] = close.pct_change(20)

    # --- Volatility ---
    tr = pd.concat([(high - low),
                    (high - close.shift(1)).abs(),
                    (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr14  = tr.rolling(14, min_periods=7).mean()
    atr100 = tr.rolling(100, min_periods=50).mean()
    out["atr_14"] = atr14
    out["atr_ratio"]  = atr14 / atr100           # >1 = volatility expanding
    out["vol_5_20"]   = ret1.rolling(5).std() / ret1.rolling(20).std()

    # --- Momentum indicators ---
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    out["rsi_14"] = 100 - 100 / (1 + rs)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()
    out["macd_hist"] = macd_line - macd_signal

    # --- Trend / structure ---
    ema20  = close.ewm(span=20, adjust=False).mean()
    ema50  = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    out["dist_ema20"]  = (close - ema20) / close
    out["dist_ema50"]  = (close - ema50) / close
    out["dist_ema200"] = (close - ema200) / close
    out["trend_20_50"]  = (ema20 > ema50).astype(int)
    out["trend_50_200"] = (ema50 > ema200).astype(int)

    # EMA slope (angle of the trend)
    out["ema50_slope"] = ema50.diff(20) / ema50.shift(20)

    # --- Bollinger Bands position ---
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_up = bb_mid + 2 * bb_std
    bb_lo = bb_mid - 2 * bb_std
    out["bb_width"] = (bb_up - bb_lo) / bb_mid
    out["bb_pos"]   = (close - bb_lo) / (bb_up - bb_lo + 1e-12)

    # --- Range / consolidation ---
    out["range_20"] = (close.rolling(20).max() - close.rolling(20).min()) / close
    # Price in the upper/lower half of the recent range
    rng_low_20  = close.rolling(20).min()
    rng_high_20 = close.rolling(20).max()
    out["pos_in_range_20"] = (close - rng_low_20) / (rng_high_20 - rng_low_20 + 1e-12)

    # Consecutive close direction streak
    up_mask = (ret1 > 0).astype(int)
    down_mask = (ret1 < 0).astype(int)
    out["consec_up"] = up_mask * (up_mask.groupby((up_mask != up_mask.shift()).cumsum()).cumcount() + 1)
    out["consec_down"] = down_mask * (down_mask.groupby((down_mask != down_mask.shift()).cumsum()).cumcount() + 1)

    # --- Temporal ---
    idx = df.index
    out["hour"] = idx.hour
    out["dow"] = idx.dayofweek

    # Sessions UTC
    out["sess_asia"]   = ((idx.hour >= 0) & (idx.hour < 8)).astype(int)
    out["sess_london"] = ((idx.hour >= 7) & (idx.hour < 16)).astype(int)
    out["sess_ny"]     = ((idx.hour >= 12) & (idx.hour < 21)).astype(int)
    out["sess_overlap"] = (out["sess_london"] & out["sess_ny"]).astype(int)

    # --- HTF alignment (optional) ---
    if htf_close is not None and len(htf_close) > 0:
        htf_ema_fast = htf_close.ewm(span=21, adjust=False).mean()
        htf_ema_slow = htf_close.ewm(span=50, adjust=False).mean()
        htf_trend = (htf_ema_fast > htf_ema_slow).astype(int) - (htf_ema_fast < htf_ema_slow).astype(int)
        # Shift by 1 HTF bar to avoid look-ahead
        htf_trend_shift = htf_trend.shift(1)
        aligned = pd.merge_asof(
            pd.DataFrame(index=out.index).sort_index(),
            htf_trend_shift.to_frame("htf_trend").sort_index(),
            left_index=True, right_index=True, direction="backward",
        )
        out["htf_trend"] = aligned["htf_trend"].fillna(0).astype(int)

    # --- Percentile ranks (for later discretization into bins) ---
    for col in ["atr_14", "atr_ratio", "rsi_14", "macd_hist", "dist_ema50",
                "dist_ema200", "bb_width", "bb_pos", "ema50_slope", "range_20",
                "pos_in_range_20", "vol_5_20"]:
        if col in out.columns:
            out[f"{col}_pr"] = _safe_pct_rank(out[col], 500)

    return out


def discretize(context: pd.DataFrame, n_bins: int = 4) -> pd.DataFrame:
    """
    Bin numerical context features into n_bins equal-frequency levels and keep
    categorical features as-is. Returns a string-bin DataFrame ready for recipe mining.
    """
    out = pd.DataFrame(index=context.index)

    # Percentile-rank features → label by quantile bucket
    pr_cols = [c for c in context.columns if c.endswith("_pr")]
    for c in pr_cols:
        base = c[:-3]
        vals = context[c]
        # Labels low / midlow / midhigh / high (for n_bins=4)
        labels = [f"{base}_q{i+1}" for i in range(n_bins)]
        # Cut into equal-width in [0, 1]
        out[base] = pd.cut(vals, bins=n_bins, labels=labels, include_lowest=True).astype(str)

    # Binary / categorical features
    for col in ["trend_20_50", "trend_50_200", "sess_asia", "sess_london",
                "sess_ny", "sess_overlap", "htf_trend"]:
        if col in context.columns:
            out[col] = col + "_" + context[col].astype(str)

    # Hour of day → 6 groups (0-3, 4-7, ..., 20-23) — keeps cardinality reasonable
    if "hour" in context.columns:
        out["hour_bucket"] = "h_" + (context["hour"] // 4).astype(str)
    # Day of week kept as-is
    if "dow" in context.columns:
        out["dow"] = "dow_" + context["dow"].astype(str)

    # Streak magnitude buckets
    if "consec_up" in context.columns:
        out["streak_up"] = pd.cut(context["consec_up"],
                                   bins=[-1, 0, 2, 4, 1000],
                                   labels=["streak_up_0", "streak_up_12", "streak_up_34", "streak_up_5p"]).astype(str)
    if "consec_down" in context.columns:
        out["streak_down"] = pd.cut(context["consec_down"],
                                     bins=[-1, 0, 2, 4, 1000],
                                     labels=["streak_down_0", "streak_down_12", "streak_down_34", "streak_down_5p"]).astype(str)

    # Drop rows with nan bins (early periods)
    out = out.dropna(how="any")
    return out
