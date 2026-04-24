#!/usr/bin/env python3
"""
Feature engineering for forex M15.

Families:
 - Returns & lagged returns (multi-horizon)
 - Volatility (realized, ATR, BB width)
 - Momentum (RSI, MACD, ROC)
 - Trend (EMA crosses, slope, distance-to-EMA)
 - Multi-timeframe context (H1 / H4 aligned as-of)
 - Session one-hots (Asia / London / NY / overlap)
 - Time features (hour, day-of-week) as cyclical
 - Regime features (vol regime, trend regime)

Every feature that would reference the future is shifted to avoid leakage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# -----------------------------------------------------------------------------
# Indicator primitives (vectorized, no TA lib needed)
# -----------------------------------------------------------------------------
def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    mid = close.rolling(period).mean()
    s = close.rolling(period).std()
    upper = mid + std * s
    lower = mid - std * s
    width = (upper - lower) / mid
    pos = (close - lower) / (upper - lower + 1e-12)
    return mid, upper, lower, width, pos


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


# -----------------------------------------------------------------------------
# Feature builders
# -----------------------------------------------------------------------------
def _add_return_features(df: pd.DataFrame, lags: list[int]) -> None:
    df["ret_1"] = df["Close"].pct_change()
    df["logret_1"] = np.log(df["Close"] / df["Close"].shift(1))
    for lag in lags:
        df[f"ret_{lag}"] = df["Close"].pct_change(lag)
        df[f"logret_{lag}"] = np.log(df["Close"] / df["Close"].shift(lag))


def _add_volatility_features(df: pd.DataFrame, atr_periods: list[int], vol_wins: list[int]) -> None:
    for p in atr_periods:
        df[f"atr_{p}"] = atr(df["High"], df["Low"], df["Close"], p)
        df[f"atr_{p}_pct"] = df[f"atr_{p}"] / df["Close"]
    for w in vol_wins:
        df[f"vol_{w}"] = df["ret_1"].rolling(w).std()
    # Volatility ratio — regime marker
    df["vol_ratio_5_20"] = df["vol_5"] / (df["vol_20"] + 1e-12)


def _add_momentum_features(df: pd.DataFrame, rsi_periods: list[int]) -> None:
    for p in rsi_periods:
        df[f"rsi_{p}"] = rsi(df["Close"], p)
    m, s, h = macd(df["Close"])
    df["macd"] = m
    df["macd_signal"] = s
    df["macd_hist"] = h
    df["roc_10"] = df["Close"].pct_change(10) * 100
    df["roc_20"] = df["Close"].pct_change(20) * 100


def _add_trend_features(df: pd.DataFrame, ema_periods: list[int]) -> None:
    for p in ema_periods:
        df[f"ema_{p}"] = ema(df["Close"], p)
        df[f"dist_ema_{p}"] = (df["Close"] - df[f"ema_{p}"]) / df["Close"]
    # Crosses
    if "ema_9" in df and "ema_21" in df:
        df["ema9_gt_ema21"] = (df["ema_9"] > df["ema_21"]).astype(int)
    if "ema_50" in df and "ema_200" in df:
        df["ema50_gt_ema200"] = (df["ema_50"] > df["ema_200"]).astype(int)
    # Slope of 50 EMA (20-bar)
    if "ema_50" in df:
        df["ema50_slope"] = df["ema_50"].diff(20) / df["ema_50"].shift(20)


def _add_bollinger_features(df: pd.DataFrame, period: int, std: float) -> None:
    mid, up, low, width, pos = bollinger(df["Close"], period, std)
    df[f"bb_width_{period}"] = width
    df[f"bb_pos_{period}"] = pos


def _add_session_features(df: pd.DataFrame, cfg: dict) -> None:
    """UTC-based session flags. Assumes df.index is UTC."""
    hours = df.index.hour
    df["session_asia"] = ((hours >= cfg["asia_start"]) & (hours < cfg["asia_end"])).astype(int)
    df["session_london"] = ((hours >= cfg["london_start"]) & (hours < cfg["london_end"])).astype(int)
    df["session_ny"] = ((hours >= cfg["ny_start"]) & (hours < cfg["ny_end"])).astype(int)
    df["session_overlap_lon_ny"] = (df["session_london"] & df["session_ny"]).astype(int)


def _add_time_features(df: pd.DataFrame) -> None:
    h = df.index.hour + df.index.minute / 60.0
    df["hour_sin"] = np.sin(2 * np.pi * h / 24)
    df["hour_cos"] = np.cos(2 * np.pi * h / 24)
    dow = df.index.dayofweek
    df["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    df["dow_cos"] = np.cos(2 * np.pi * dow / 7)


def _add_mtf_context(df: pd.DataFrame, htf: Optional[pd.DataFrame], suffix: str) -> None:
    """Align higher-timeframe features on the lower TF with as-of merge (no look-ahead)."""
    if htf is None:
        return
    h = htf.copy()
    h[f"rsi_14_{suffix}"] = rsi(h["Close"], 14)
    h[f"ema_21_{suffix}"] = ema(h["Close"], 21)
    h[f"ema_50_{suffix}"] = ema(h["Close"], 50)
    h[f"dist_ema_21_{suffix}"] = (h["Close"] - h[f"ema_21_{suffix}"]) / h["Close"]
    h[f"dist_ema_50_{suffix}"] = (h["Close"] - h[f"ema_50_{suffix}"]) / h["Close"]
    h[f"atr_14_pct_{suffix}"] = atr(h["High"], h["Low"], h["Close"], 14) / h["Close"]
    h[f"trend_{suffix}"] = (h[f"ema_21_{suffix}"] > h[f"ema_50_{suffix}"]).astype(int)

    cols = [c for c in h.columns if c.endswith(f"_{suffix}")]
    # Shift HTF by 1 bar to guarantee no lookahead (the bar at time t closes at t+TF)
    h_shift = h[cols].shift(1)

    # merge_asof requires sorted indexes
    merged = pd.merge_asof(
        df.sort_index(),
        h_shift.sort_index(),
        left_index=True, right_index=True,
        direction="backward",
    )
    for c in cols:
        df[c] = merged[c].values


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def build_features(
    df_m15: pd.DataFrame,
    df_h1: Optional[pd.DataFrame] = None,
    df_h4: Optional[pd.DataFrame] = None,
    cfg: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Full feature pipeline. Returns the enriched M15 DataFrame.
    The caller is responsible for dropping initial NaN rows after labeling.
    """
    if cfg is None:
        cfg = _default_feature_cfg()

    out = df_m15.copy()
    out.index.name = "datetime"

    _add_return_features(out, cfg["return_lags"])
    _add_volatility_features(out, cfg["atr_periods"], cfg["volatility_windows"])
    _add_momentum_features(out, cfg["rsi_periods"])
    _add_trend_features(out, cfg["ema_periods"])
    _add_bollinger_features(out, cfg["bb_period"], cfg["bb_std"])
    _add_session_features(out, cfg["sessions"])
    _add_time_features(out)
    _add_mtf_context(out, df_h1, "h1")
    _add_mtf_context(out, df_h4, "h4")

    return out


def _default_feature_cfg() -> dict:
    return {
        "return_lags": [1, 3, 5, 10, 20],
        "volatility_windows": [5, 20, 50],
        "atr_periods": [14, 50],
        "rsi_periods": [7, 14, 21],
        "ema_periods": [9, 21, 50, 200],
        "bb_period": 20,
        "bb_std": 2.0,
        "sessions": {
            "asia_start": 0, "asia_end": 8,
            "london_start": 7, "london_end": 16,
            "ny_start": 12, "ny_end": 21,
        },
    }


FEATURE_BLACKLIST = {
    "Open", "High", "Low", "Close", "TickVolume", "Spread",
    # Raw EMAs would leak absolute price level across train/test — keep only distances.
    "ema_9", "ema_21", "ema_50", "ema_200",
    "atr_14", "atr_50",
}


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    """Return the columns that the model should consume."""
    return [c for c in df.columns if c not in FEATURE_BLACKLIST and not c.startswith("label")]
