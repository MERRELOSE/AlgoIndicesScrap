#!/usr/bin/env python3
"""
Event detection: identify "big move" opportunities.

A big move at bar t is defined as: within the next `horizon` bars, price reaches
at least `target_atr` * ATR in one direction BEFORE the opposite barrier at
`stop_atr` * ATR is hit.

This mirrors the triple-barrier labeling but with a stricter focus on
high-R:R setups (e.g., 3R gains achieved before 1R losses).

We record both direction (+1 bullish, -1 bearish, 0 neither) and the realized
magnitude so downstream analysis can examine conditions that precede large moves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class EventConfig:
    target_atr: float = 3.0       # Take-profit barrier (how big the move must be)
    stop_atr: float = 1.0         # Stop barrier (what counts as "failed")
    horizon: int = 24             # How many bars forward to look
    atr_col: str = "atr_14"


def detect_big_moves(df: pd.DataFrame, cfg: EventConfig) -> pd.DataFrame:
    """
    For each bar t, label whether a big move happens before a stop is hit.

    Returns a DataFrame indexed like df with columns:
      - event_long   : 1 if long TP (target_atr) hit before long SL (stop_atr), else 0
      - event_short  : 1 if short TP hit before short SL, else 0
      - first_dir    : +1 bull / -1 bear / 0 neither / NaN if undefined
      - r_realized   : the R realized at the first barrier hit (target_atr or -stop_atr)
      - bars_to_event: bars until first barrier hit
    """
    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values
    atrs = df[cfg.atr_col].values
    n = len(df)

    event_long = np.full(n, np.nan)
    event_short = np.full(n, np.nan)
    first_dir = np.full(n, np.nan)
    r_realized = np.full(n, np.nan)
    bars_to_event = np.full(n, np.nan)

    for i in range(n):
        a = atrs[i]
        if np.isnan(a) or a <= 0 or i + cfg.horizon >= n:
            continue
        entry = closes[i]
        tp_long  = entry + cfg.target_atr * a
        sl_long  = entry - cfg.stop_atr * a
        tp_short = entry - cfg.target_atr * a
        sl_short = entry + cfg.stop_atr * a

        # Scan forward
        long_out = 0
        short_out = 0
        bars_used = cfg.horizon
        realized_r = 0.0
        direction = 0

        for k in range(1, cfg.horizon + 1):
            hi, lo = highs[i + k], lows[i + k]

            # Long barrier check
            long_tp_hit = hi >= tp_long
            long_sl_hit = lo <= sl_long
            short_tp_hit = lo <= tp_short
            short_sl_hit = hi >= sl_short

            # Determine direction & magnitude on first terminal event
            if direction == 0:
                # Bullish: long TP first OR short SL first (same thing)
                if long_tp_hit and not long_sl_hit:
                    direction = +1
                    realized_r = cfg.target_atr
                    bars_used = k
                    long_out = 1
                elif long_sl_hit and not long_tp_hit:
                    # Bearish move — long stop hit
                    direction = -1
                    realized_r = -cfg.stop_atr
                    bars_used = k
                    long_out = 0
                elif long_tp_hit and long_sl_hit:
                    # Same-bar tie: conservative — treat as stop
                    direction = -1
                    realized_r = -cfg.stop_atr
                    bars_used = k

                # Independently compute short outcome on the same first-terminal basis
                if short_tp_hit and not short_sl_hit:
                    short_out = 1
                elif short_sl_hit and not short_tp_hit:
                    short_out = 0
                elif short_tp_hit and short_sl_hit:
                    short_out = 0

                if direction != 0:
                    break

        event_long[i] = long_out
        event_short[i] = short_out
        first_dir[i] = direction
        r_realized[i] = realized_r
        bars_to_event[i] = bars_used

    out = pd.DataFrame({
        "event_long": event_long,
        "event_short": event_short,
        "first_dir": first_dir,
        "r_realized": r_realized,
        "bars_to_event": bars_to_event,
    }, index=df.index)
    return out


def base_rates(events: pd.DataFrame) -> dict:
    """Background rates - how often does the target move happen in random samples?"""
    d = events.dropna(subset=["event_long", "event_short"])
    if d.empty:
        return {"long": 0.0, "short": 0.0, "any_big_move": 0.0, "n": 0}
    return {
        "long": float(d["event_long"].mean()),
        "short": float(d["event_short"].mean()),
        "any_big_move": float(((d["event_long"] == 1) | (d["event_short"] == 1)).mean()),
        "n": int(len(d)),
    }
