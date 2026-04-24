#!/usr/bin/env python3
"""
BEHAVIOR DISCOVERY ENGINE
=========================
Goal: Discover PROVEN, REPEATED, VALIDATED behaviors in synthetic indices.

NOT prediction. NOT ML. Just facts:
  "When X happens, Y follows Z% of the time (N occurrences, p-value < 0.05)"

Each behavior must pass 3 tests:
  1. FREQUENCY: happened enough times (min 30 occurrences)
  2. SIGNIFICANCE: statistically different from random (p < 0.05)
  3. CONSISTENCY: works in both first half AND second half of data (not a fluke)
"""

import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats
import warnings
warnings.filterwarnings('ignore')


# ============================================================
# CORE: Behavior validation framework
# ============================================================

class Behavior:
    """A single discovered behavior with full statistical validation"""

    def __init__(self, name, condition_desc, outcome_desc):
        self.name = name
        self.condition_desc = condition_desc
        self.outcome_desc = outcome_desc
        self.occurrences = 0
        self.outcome_rate = 0.0
        self.baseline_rate = 0.0
        self.edge = 0.0  # outcome_rate - baseline_rate
        self.p_value = 1.0
        self.first_half_rate = 0.0
        self.second_half_rate = 0.0
        self.is_valid = False
        self.avg_return_after = 0.0
        self.median_return_after = 0.0
        self.details = {}

    def validate(self, outcomes, baseline_rate, first_half_outcomes=None, second_half_outcomes=None):
        """Validate behavior with 3 tests"""
        self.occurrences = len(outcomes)
        if self.occurrences < 30:
            self.is_valid = False
            return

        self.outcome_rate = np.mean(outcomes)
        self.baseline_rate = baseline_rate
        self.edge = self.outcome_rate - baseline_rate

        # Test 1: Statistical significance (binomial test)
        successes = int(np.sum(outcomes))
        self.p_value = stats.binomtest(successes, self.occurrences, baseline_rate).pvalue

        # Test 2: Consistency across time periods
        if first_half_outcomes is not None and second_half_outcomes is not None:
            if len(first_half_outcomes) >= 10 and len(second_half_outcomes) >= 10:
                self.first_half_rate = np.mean(first_half_outcomes)
                self.second_half_rate = np.mean(second_half_outcomes)
            else:
                self.first_half_rate = self.outcome_rate
                self.second_half_rate = self.outcome_rate

        # Valid if: significant + consistent direction in both halves
        same_direction = (
            (self.first_half_rate > baseline_rate and self.second_half_rate > baseline_rate) or
            (self.first_half_rate < baseline_rate and self.second_half_rate < baseline_rate)
        )

        self.is_valid = (
            self.p_value < 0.05 and
            self.occurrences >= 30 and
            same_direction
        )

    def __str__(self):
        status = "VALID" if self.is_valid else "REJECTED"
        return (
            f"[{status}] {self.name}\n"
            f"  When: {self.condition_desc}\n"
            f"  Then: {self.outcome_desc}\n"
            f"  Rate: {self.outcome_rate*100:.1f}% vs baseline {self.baseline_rate*100:.1f}% "
            f"(edge: {self.edge*100:+.1f}%)\n"
            f"  Occurrences: {self.occurrences} | p-value: {self.p_value:.4f}\n"
            f"  Consistency: 1st half={self.first_half_rate*100:.1f}% | 2nd half={self.second_half_rate*100:.1f}%"
        )


# ============================================================
# FEATURE COMPUTATION (for conditions)
# ============================================================

def prepare_data(df):
    """Add all necessary columns for behavior analysis"""
    df = df.copy()

    # Returns
    df['ret'] = df['Close'].pct_change()
    df['ret_abs'] = df['ret'].abs()
    df['log_ret'] = np.log(df['Close'] / df['Close'].shift(1))
    df['direction'] = (df['ret'] > 0).astype(int)  # 1=up, 0=down

    # Candle properties
    df['body'] = df['Close'] - df['Open']
    df['body_abs'] = df['body'].abs()
    df['range'] = df['High'] - df['Low']
    df['upper_wick'] = df['High'] - df[['Open', 'Close']].max(axis=1)
    df['lower_wick'] = df[['Open', 'Close']].min(axis=1) - df['Low']
    df['body_ratio'] = df['body_abs'] / df['range'].replace(0, np.nan)
    df['is_bullish'] = (df['Close'] > df['Open']).astype(int)
    df['is_doji'] = (df['body_ratio'] < 0.1).astype(int)

    # Volatility
    for w in [5, 10, 20]:
        df[f'vol_{w}'] = df['ret'].rolling(w).std()
        df[f'atr_{w}'] = df['range'].rolling(w).mean()

    df['vol_ratio'] = df['vol_5'] / df['vol_20']

    # Trend (EMAs)
    for span in [5, 10, 20, 50]:
        df[f'ema_{span}'] = df['Close'].ewm(span=span, adjust=False).mean()

    df['trend_short'] = (df['ema_5'] > df['ema_20']).astype(int)  # 1=uptrend
    df['trend_long'] = (df['ema_20'] > df['ema_50']).astype(int)

    df['dist_ema20'] = (df['Close'] - df['ema_20']) / df['ema_20'] * 100  # % away from EMA20

    # RSI
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))

    # Consecutive moves
    df['consec_up'] = 0
    df['consec_down'] = 0
    up_count = 0
    down_count = 0
    for i in range(len(df)):
        if df['ret'].iloc[i] > 0:
            up_count += 1
            down_count = 0
        elif df['ret'].iloc[i] < 0:
            down_count += 1
            up_count = 0
        else:
            up_count = 0
            down_count = 0
        df.iloc[i, df.columns.get_loc('consec_up')] = up_count
        df.iloc[i, df.columns.get_loc('consec_down')] = down_count

    # Spike detection
    ret_std = df['ret'].rolling(100, min_periods=50).std()
    ret_mean = df['ret'].rolling(100, min_periods=50).mean()
    df['is_crash_spike'] = (df['ret'] < ret_mean - 3 * ret_std).astype(int)
    df['is_boom_spike'] = (df['ret'] > ret_mean + 3 * ret_std).astype(int)

    # Time since last spike
    df['candles_since_crash'] = 0
    count = 999
    for i in range(len(df)):
        if df['is_crash_spike'].iloc[i] == 1:
            count = 0
        else:
            count += 1
        df.iloc[i, df.columns.get_loc('candles_since_crash')] = count

    # Higher highs / lower lows
    df['higher_high'] = (df['High'] > df['High'].shift(1)).astype(int)
    df['lower_low'] = (df['Low'] < df['Low'].shift(1)).astype(int)
    df['hh_streak'] = df['higher_high'].rolling(5).sum()
    df['ll_streak'] = df['lower_low'].rolling(5).sum()

    # Volume of movement (range relative to average)
    df['range_vs_avg'] = df['range'] / df['atr_20']

    # Time features
    if hasattr(df.index, 'hour'):
        df['hour'] = df.index.hour
        df['day_of_week'] = df.index.dayofweek

    # Next candle outcomes (for measuring behaviors)
    df['next_ret'] = df['ret'].shift(-1)
    df['next_dir'] = df['direction'].shift(-1)  # 1=up, 0=down
    df['next_3_ret'] = df['Close'].shift(-3) / df['Close'] - 1
    df['next_5_ret'] = df['Close'].shift(-5) / df['Close'] - 1
    df['next_10_ret'] = df['Close'].shift(-10) / df['Close'] - 1

    # Max favorable / adverse excursion in next N candles
    for n in [3, 5, 10]:
        future_highs = df['High'].rolling(n).max().shift(-n)
        future_lows = df['Low'].rolling(n).min().shift(-n)
        df[f'max_up_{n}'] = (future_highs - df['Close']) / df['Close']
        df[f'max_down_{n}'] = (df['Close'] - future_lows) / df['Close']

    return df.dropna()


# ============================================================
# BEHAVIOR DISCOVERY FUNCTIONS
# ============================================================

def discover_consecutive_behaviors(df, baseline_up):
    """What happens after N consecutive up/down candles?"""
    behaviors = []

    for n in range(2, 8):
        # After N consecutive UP candles
        mask = df['consec_up'] == n
        if mask.sum() >= 20:
            b = Behavior(
                f"after_{n}_consecutive_up",
                f"{n} consecutive bullish candles",
                "next candle direction"
            )
            outcomes = df.loc[mask, 'next_dir'].values
            mid = len(df) // 2
            first = df.iloc[:mid]
            second = df.iloc[mid:]
            b.validate(
                outcomes, baseline_up,
                first.loc[first.index.isin(df[mask].index), 'next_dir'].values,
                second.loc[second.index.isin(df[mask].index), 'next_dir'].values
            )
            b.avg_return_after = df.loc[mask, 'next_ret'].mean()
            b.details['avg_next_3_ret'] = df.loc[mask, 'next_3_ret'].mean()
            b.details['avg_next_5_ret'] = df.loc[mask, 'next_5_ret'].mean()
            behaviors.append(b)

        # After N consecutive DOWN candles
        mask = df['consec_down'] == n
        if mask.sum() >= 20:
            b = Behavior(
                f"after_{n}_consecutive_down",
                f"{n} consecutive bearish candles",
                "next candle direction"
            )
            outcomes = df.loc[mask, 'next_dir'].values
            mid = len(df) // 2
            first = df.iloc[:mid]
            second = df.iloc[mid:]
            b.validate(
                outcomes, baseline_up,
                first.loc[first.index.isin(df[mask].index), 'next_dir'].values,
                second.loc[second.index.isin(df[mask].index), 'next_dir'].values
            )
            b.avg_return_after = df.loc[mask, 'next_ret'].mean()
            b.details['avg_next_3_ret'] = df.loc[mask, 'next_3_ret'].mean()
            b.details['avg_next_5_ret'] = df.loc[mask, 'next_5_ret'].mean()
            behaviors.append(b)

    return behaviors


def discover_volatility_behaviors(df, baseline_up):
    """What happens after periods of low/high volatility?"""
    behaviors = []

    # Volatility percentiles
    vol_p20 = df['vol_5'].quantile(0.20)
    vol_p40 = df['vol_5'].quantile(0.40)
    vol_p60 = df['vol_5'].quantile(0.60)
    vol_p80 = df['vol_5'].quantile(0.80)

    conditions = [
        ('very_low_volatility', df['vol_5'] < vol_p20, f"volatility in bottom 20% (<{vol_p20:.5f})"),
        ('low_volatility', (df['vol_5'] >= vol_p20) & (df['vol_5'] < vol_p40), f"volatility 20-40th percentile"),
        ('high_volatility', (df['vol_5'] >= vol_p60) & (df['vol_5'] < vol_p80), f"volatility 60-80th percentile"),
        ('very_high_volatility', df['vol_5'] >= vol_p80, f"volatility in top 20% (>{vol_p80:.5f})"),
    ]

    mid = len(df) // 2
    first = df.iloc[:mid]
    second = df.iloc[mid:]

    for name, mask, desc in conditions:
        # Direction after
        b = Behavior(f"{name}_direction", desc, "next candle goes UP")
        outcomes = df.loc[mask, 'next_dir'].values
        b.validate(
            outcomes, baseline_up,
            first.loc[first.index.isin(df[mask].index), 'next_dir'].values,
            second.loc[second.index.isin(df[mask].index), 'next_dir'].values
        )
        b.avg_return_after = df.loc[mask, 'next_ret'].mean()
        b.details['avg_next_5_ret'] = df.loc[mask, 'next_5_ret'].mean()
        b.details['avg_next_10_ret'] = df.loc[mask, 'next_10_ret'].mean()
        b.details['avg_max_up_5'] = df.loc[mask, 'max_up_5'].mean()
        b.details['avg_max_down_5'] = df.loc[mask, 'max_down_5'].mean()
        behaviors.append(b)

    # Vol contraction then expansion
    mask = (df['vol_ratio'] < 0.6)
    b = Behavior(
        "vol_squeeze",
        "volatility squeeze (5-period vol < 60% of 20-period vol)",
        "large move in next 5 candles"
    )
    # Outcome: was the next 5-candle move bigger than average?
    avg_5_move = df['next_5_ret'].abs().mean()
    outcomes = (df.loc[mask, 'next_5_ret'].abs() > avg_5_move).astype(int).values
    b.validate(
        outcomes, 0.5,
        (first.loc[first.index.isin(df[mask].index), 'next_5_ret'].abs() > avg_5_move).astype(int).values,
        (second.loc[second.index.isin(df[mask].index), 'next_5_ret'].abs() > avg_5_move).astype(int).values
    )
    b.details['avg_abs_move_5'] = df.loc[mask, 'next_5_ret'].abs().mean()
    b.details['normal_abs_move_5'] = avg_5_move
    behaviors.append(b)

    return behaviors


def discover_spike_behaviors(df, baseline_up):
    """What happens before and after crash spikes?"""
    behaviors = []
    mid = len(df) // 2
    first = df.iloc[:mid]
    second = df.iloc[mid:]

    # === POST-CRASH behaviors ===
    for n_after in [1, 3, 5, 10, 20]:
        mask = df['is_crash_spike'].shift(1) == 1  # candle RIGHT AFTER a crash
        if n_after > 1:
            # N candles after crash
            for shift in range(2, n_after + 1):
                mask = mask | (df['is_crash_spike'].shift(shift) == 1)

        if n_after == 1:
            mask = df['is_crash_spike'].shift(1) == 1

            b = Behavior(
                f"post_crash_1_candle",
                "1 candle after a crash spike",
                "next candle goes UP (bounce)"
            )
            outcomes = df.loc[mask, 'next_dir'].values
            b.validate(
                outcomes, baseline_up,
                first.loc[first.index.isin(df[mask].index), 'next_dir'].values,
                second.loc[second.index.isin(df[mask].index), 'next_dir'].values
            )
            b.avg_return_after = df.loc[mask, 'next_ret'].mean()
            b.details['avg_next_5_ret'] = df.loc[mask, 'next_5_ret'].mean()
            behaviors.append(b)

        # Return N candles after crash
        mask_crash = df['is_crash_spike'] == 1
        if mask_crash.sum() >= 10:
            ret_col = f'next_{n_after}_ret' if f'next_{n_after}_ret' in df.columns else 'next_5_ret'
            if ret_col in df.columns:
                b = Behavior(
                    f"crash_recovery_{n_after}_candles",
                    f"a crash spike just occurred",
                    f"price recovers within {n_after} candles"
                )
                recovery = (df.loc[mask_crash, ret_col] > 0).astype(int).values
                b.validate(
                    recovery, 0.5,
                    (first.loc[first.index.isin(df[mask_crash].index), ret_col] > 0).astype(int).values if len(first.loc[first.index.isin(df[mask_crash].index)]) > 0 else np.array([]),
                    (second.loc[second.index.isin(df[mask_crash].index), ret_col] > 0).astype(int).values if len(second.loc[second.index.isin(df[mask_crash].index)]) > 0 else np.array([])
                )
                b.avg_return_after = df.loc[mask_crash, ret_col].mean()
                b.details['median_return'] = df.loc[mask_crash, ret_col].median()
                behaviors.append(b)

    # === TIME SINCE LAST CRASH ===
    for threshold in [50, 100, 200]:
        mask = df['candles_since_crash'] > threshold
        b = Behavior(
            f"long_since_crash_{threshold}",
            f"more than {threshold} candles since last crash spike",
            "crash spike happens within next 10 candles"
        )
        # Check if a crash happens in next 10 candles
        crash_next_10 = df['is_crash_spike'].rolling(10).max().shift(-10)
        outcomes = crash_next_10.loc[mask].dropna().values
        b.validate(
            outcomes, df['is_crash_spike'].mean() * 10,  # baseline: random probability over 10 candles
            crash_next_10.loc[first.index.intersection(df[mask].index)].dropna().values,
            crash_next_10.loc[second.index.intersection(df[mask].index)].dropna().values
        )
        behaviors.append(b)

    return behaviors


def discover_rsi_behaviors(df, baseline_up):
    """Behaviors at RSI extremes"""
    behaviors = []
    mid = len(df) // 2
    first = df.iloc[:mid]
    second = df.iloc[mid:]

    rsi_levels = [
        ('rsi_oversold_20', df['rsi'] < 20, "RSI < 20 (deeply oversold)"),
        ('rsi_oversold_30', (df['rsi'] >= 20) & (df['rsi'] < 30), "RSI between 20-30 (oversold)"),
        ('rsi_neutral_low', (df['rsi'] >= 40) & (df['rsi'] < 50), "RSI 40-50 (neutral low)"),
        ('rsi_neutral_high', (df['rsi'] >= 50) & (df['rsi'] < 60), "RSI 50-60 (neutral high)"),
        ('rsi_overbought_70', (df['rsi'] >= 70) & (df['rsi'] < 80), "RSI between 70-80 (overbought)"),
        ('rsi_overbought_80', df['rsi'] >= 80, "RSI > 80 (deeply overbought)"),
    ]

    for name, mask, desc in rsi_levels:
        # Next candle direction
        b = Behavior(f"{name}_next_dir", desc, "next candle goes UP")
        outcomes = df.loc[mask, 'next_dir'].values
        b.validate(
            outcomes, baseline_up,
            first.loc[first.index.isin(df[mask].index), 'next_dir'].values,
            second.loc[second.index.isin(df[mask].index), 'next_dir'].values
        )
        b.avg_return_after = df.loc[mask, 'next_ret'].mean()
        b.details['avg_next_5_ret'] = df.loc[mask, 'next_5_ret'].mean()
        behaviors.append(b)

        # Next 5 candles direction
        b5 = Behavior(f"{name}_next_5", desc, "price goes UP in next 5 candles")
        outcomes_5 = (df.loc[mask, 'next_5_ret'] > 0).astype(int).values
        b5.validate(
            outcomes_5, 0.5,
            (first.loc[first.index.isin(df[mask].index), 'next_5_ret'] > 0).astype(int).values,
            (second.loc[second.index.isin(df[mask].index), 'next_5_ret'] > 0).astype(int).values
        )
        b5.avg_return_after = df.loc[mask, 'next_5_ret'].mean()
        behaviors.append(b5)

    return behaviors


def discover_trend_structure_behaviors(df, baseline_up):
    """Behaviors based on trend structure (HH/LL, EMA position)"""
    behaviors = []
    mid = len(df) // 2
    first = df.iloc[:mid]
    second = df.iloc[mid:]

    # Price far from EMA20
    for threshold in [1.0, 2.0, 3.0]:
        # Price far ABOVE ema20
        mask = df['dist_ema20'] > threshold
        b = Behavior(
            f"far_above_ema20_{threshold}pct",
            f"price is {threshold}%+ above EMA20 (overextended UP)",
            "next candle goes DOWN (mean reversion)"
        )
        outcomes = (1 - df.loc[mask, 'next_dir']).values  # inverted: we check DOWN
        b.validate(
            outcomes, 1 - baseline_up,
            (1 - first.loc[first.index.isin(df[mask].index), 'next_dir']).values,
            (1 - second.loc[second.index.isin(df[mask].index), 'next_dir']).values
        )
        b.avg_return_after = df.loc[mask, 'next_ret'].mean()
        b.details['avg_next_5_ret'] = df.loc[mask, 'next_5_ret'].mean()
        behaviors.append(b)

        # Price far BELOW ema20
        mask = df['dist_ema20'] < -threshold
        b = Behavior(
            f"far_below_ema20_{threshold}pct",
            f"price is {threshold}%+ below EMA20 (overextended DOWN)",
            "next candle goes UP (mean reversion)"
        )
        outcomes = df.loc[mask, 'next_dir'].values
        b.validate(
            outcomes, baseline_up,
            first.loc[first.index.isin(df[mask].index), 'next_dir'].values,
            second.loc[second.index.isin(df[mask].index), 'next_dir'].values
        )
        b.avg_return_after = df.loc[mask, 'next_ret'].mean()
        b.details['avg_next_5_ret'] = df.loc[mask, 'next_5_ret'].mean()
        behaviors.append(b)

    # Higher highs / lower lows streaks
    for count in [3, 4, 5]:
        mask = df['hh_streak'] >= count
        b = Behavior(
            f"{count}_higher_highs",
            f"{count}+ higher highs in last 5 candles (strong uptrend)",
            "next candle continues UP"
        )
        outcomes = df.loc[mask, 'next_dir'].values
        b.validate(
            outcomes, baseline_up,
            first.loc[first.index.isin(df[mask].index), 'next_dir'].values,
            second.loc[second.index.isin(df[mask].index), 'next_dir'].values
        )
        b.avg_return_after = df.loc[mask, 'next_ret'].mean()
        behaviors.append(b)

        mask = df['ll_streak'] >= count
        b = Behavior(
            f"{count}_lower_lows",
            f"{count}+ lower lows in last 5 candles (strong downtrend)",
            "next candle continues DOWN"
        )
        outcomes = (1 - df.loc[mask, 'next_dir']).values
        b.validate(
            outcomes, 1 - baseline_up,
            (1 - first.loc[first.index.isin(df[mask].index), 'next_dir']).values,
            (1 - second.loc[second.index.isin(df[mask].index), 'next_dir']).values
        )
        b.avg_return_after = df.loc[mask, 'next_ret'].mean()
        behaviors.append(b)

    # EMA crossover behaviors
    # Bullish cross: ema5 crosses above ema20
    ema5_above = df['ema_5'] > df['ema_20']
    bullish_cross = ema5_above & (~ema5_above.shift(1).fillna(False))

    b = Behavior(
        "bullish_ema_cross",
        "EMA5 crosses above EMA20 (bullish crossover)",
        "price goes UP in next 5 candles"
    )
    mask = bullish_cross
    outcomes = (df.loc[mask, 'next_5_ret'] > 0).astype(int).values
    b.validate(
        outcomes, 0.5,
        (first.loc[first.index.isin(df[mask].index), 'next_5_ret'] > 0).astype(int).values,
        (second.loc[second.index.isin(df[mask].index), 'next_5_ret'] > 0).astype(int).values
    )
    b.avg_return_after = df.loc[mask, 'next_5_ret'].mean()
    behaviors.append(b)

    # Bearish cross
    bearish_cross = (~ema5_above) & (ema5_above.shift(1).fillna(True))
    b = Behavior(
        "bearish_ema_cross",
        "EMA5 crosses below EMA20 (bearish crossover)",
        "price goes DOWN in next 5 candles"
    )
    mask = bearish_cross
    outcomes = (df.loc[mask, 'next_5_ret'] < 0).astype(int).values
    b.validate(
        outcomes, 0.5,
        (first.loc[first.index.isin(df[mask].index), 'next_5_ret'] < 0).astype(int).values,
        (second.loc[second.index.isin(df[mask].index), 'next_5_ret'] < 0).astype(int).values
    )
    b.avg_return_after = df.loc[mask, 'next_5_ret'].mean()
    behaviors.append(b)

    return behaviors


def discover_candle_pattern_behaviors(df, baseline_up):
    """Behaviors based on candle patterns"""
    behaviors = []
    mid = len(df) // 2
    first = df.iloc[:mid]
    second = df.iloc[mid:]

    # Big candle followed by...
    range_p80 = df['range_vs_avg'].quantile(0.80)
    range_p90 = df['range_vs_avg'].quantile(0.90)

    # Large bullish candle
    mask = (df['range_vs_avg'] > range_p80) & (df['is_bullish'] == 1)
    b = Behavior(
        "big_bull_candle",
        "large bullish candle (range in top 20%)",
        "next candle continues UP (momentum)"
    )
    outcomes = df.loc[mask, 'next_dir'].values
    b.validate(
        outcomes, baseline_up,
        first.loc[first.index.isin(df[mask].index), 'next_dir'].values,
        second.loc[second.index.isin(df[mask].index), 'next_dir'].values
    )
    b.avg_return_after = df.loc[mask, 'next_ret'].mean()
    behaviors.append(b)

    # Large bearish candle
    mask = (df['range_vs_avg'] > range_p80) & (df['is_bullish'] == 0)
    b = Behavior(
        "big_bear_candle",
        "large bearish candle (range in top 20%)",
        "next candle continues DOWN (momentum)"
    )
    outcomes = (1 - df.loc[mask, 'next_dir']).values
    b.validate(
        outcomes, 1 - baseline_up,
        (1 - first.loc[first.index.isin(df[mask].index), 'next_dir']).values,
        (1 - second.loc[second.index.isin(df[mask].index), 'next_dir']).values
    )
    b.avg_return_after = df.loc[mask, 'next_ret'].mean()
    behaviors.append(b)

    # Doji candle
    mask = df['is_doji'] == 1
    b = Behavior(
        "doji_candle",
        "doji candle (body < 10% of range = indecision)",
        "next candle is more volatile (range > average)"
    )
    outcomes = (df.loc[mask, 'range_vs_avg'].shift(-1) > 1.0).astype(int).values
    b.validate(
        outcomes, (df['range_vs_avg'] > 1.0).mean(),
        (first.loc[first.index.isin(df[mask].index), 'range_vs_avg'].shift(-1) > 1.0).astype(int).values if len(first[first.index.isin(df[mask].index)]) > 0 else np.array([]),
        (second.loc[second.index.isin(df[mask].index), 'range_vs_avg'].shift(-1) > 1.0).astype(int).values if len(second[second.index.isin(df[mask].index)]) > 0 else np.array([])
    )
    behaviors.append(b)

    # Hammer (long lower wick, small body at top)
    mask = (df['lower_wick'] > 2 * df['body_abs']) & (df['upper_wick'] < df['body_abs']) & (df['range'] > 0)
    b = Behavior(
        "hammer_candle",
        "hammer pattern (long lower wick, rejection of lows)",
        "next candle goes UP (reversal)"
    )
    outcomes = df.loc[mask, 'next_dir'].values
    b.validate(
        outcomes, baseline_up,
        first.loc[first.index.isin(df[mask].index), 'next_dir'].values,
        second.loc[second.index.isin(df[mask].index), 'next_dir'].values
    )
    b.avg_return_after = df.loc[mask, 'next_ret'].mean()
    behaviors.append(b)

    # Shooting star (long upper wick)
    mask = (df['upper_wick'] > 2 * df['body_abs']) & (df['lower_wick'] < df['body_abs']) & (df['range'] > 0)
    b = Behavior(
        "shooting_star",
        "shooting star (long upper wick, rejection of highs)",
        "next candle goes DOWN (reversal)"
    )
    outcomes = (1 - df.loc[mask, 'next_dir']).values
    b.validate(
        outcomes, 1 - baseline_up,
        (1 - first.loc[first.index.isin(df[mask].index), 'next_dir']).values,
        (1 - second.loc[second.index.isin(df[mask].index), 'next_dir']).values
    )
    b.avg_return_after = df.loc[mask, 'next_ret'].mean()
    behaviors.append(b)

    return behaviors


def discover_time_behaviors(df, baseline_up):
    """Time-of-day and day-of-week behaviors"""
    behaviors = []

    if 'hour' not in df.columns:
        return behaviors

    mid = len(df) // 2
    first = df.iloc[:mid]
    second = df.iloc[mid:]

    # Hourly behaviors
    for h in range(0, 24, 4):  # Check in 4-hour blocks
        h_end = h + 4
        mask = (df['hour'] >= h) & (df['hour'] < h_end)

        b = Behavior(
            f"hour_{h}_{h_end}_bullish",
            f"time is {h:02d}:00-{h_end:02d}:00 UTC",
            "candle goes UP"
        )
        outcomes = df.loc[mask, 'direction'].values
        b.validate(
            outcomes, baseline_up,
            first.loc[first.index.isin(df[mask].index), 'direction'].values,
            second.loc[second.index.isin(df[mask].index), 'direction'].values
        )
        b.avg_return_after = df.loc[mask, 'ret'].mean()
        behaviors.append(b)

    # Day of week behaviors
    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    for d in range(7):
        mask = df['day_of_week'] == d
        if mask.sum() < 30:
            continue

        b = Behavior(
            f"day_{day_names[d]}_bullish",
            f"day is {day_names[d]}",
            "candle goes UP"
        )
        outcomes = df.loc[mask, 'direction'].values
        b.validate(
            outcomes, baseline_up,
            first.loc[first.index.isin(df[mask].index), 'direction'].values,
            second.loc[second.index.isin(df[mask].index), 'direction'].values
        )
        b.avg_return_after = df.loc[mask, 'ret'].mean()
        behaviors.append(b)

    return behaviors


def discover_combined_behaviors(df, baseline_up):
    """Multi-condition behaviors (combinations)"""
    behaviors = []
    mid = len(df) // 2
    first = df.iloc[:mid]
    second = df.iloc[mid:]

    # Low vol + oversold RSI -> bounce?
    mask = (df['vol_5'] < df['vol_5'].quantile(0.3)) & (df['rsi'] < 35)
    b = Behavior(
        "low_vol_oversold",
        "low volatility + RSI oversold (<35)",
        "price goes UP in next 5 candles"
    )
    outcomes = (df.loc[mask, 'next_5_ret'] > 0).astype(int).values
    b.validate(
        outcomes, 0.5,
        (first.loc[first.index.isin(df[mask].index), 'next_5_ret'] > 0).astype(int).values,
        (second.loc[second.index.isin(df[mask].index), 'next_5_ret'] > 0).astype(int).values
    )
    b.avg_return_after = df.loc[mask, 'next_5_ret'].mean()
    behaviors.append(b)

    # High vol + overbought RSI -> crash?
    mask = (df['vol_5'] > df['vol_5'].quantile(0.7)) & (df['rsi'] > 65)
    b = Behavior(
        "high_vol_overbought",
        "high volatility + RSI overbought (>65)",
        "price goes DOWN in next 5 candles"
    )
    outcomes = (df.loc[mask, 'next_5_ret'] < 0).astype(int).values
    b.validate(
        outcomes, 0.5,
        (first.loc[first.index.isin(df[mask].index), 'next_5_ret'] < 0).astype(int).values,
        (second.loc[second.index.isin(df[mask].index), 'next_5_ret'] < 0).astype(int).values
    )
    b.avg_return_after = df.loc[mask, 'next_5_ret'].mean()
    behaviors.append(b)

    # Trend + momentum alignment
    mask = (df['trend_short'] == 1) & (df['trend_long'] == 1) & (df['rsi'] > 50) & (df['rsi'] < 70)
    b = Behavior(
        "full_bull_alignment",
        "all EMAs bullish + RSI 50-70 (confirmed uptrend with room)",
        "next candle goes UP"
    )
    outcomes = df.loc[mask, 'next_dir'].values
    b.validate(
        outcomes, baseline_up,
        first.loc[first.index.isin(df[mask].index), 'next_dir'].values,
        second.loc[second.index.isin(df[mask].index), 'next_dir'].values
    )
    b.avg_return_after = df.loc[mask, 'next_ret'].mean()
    behaviors.append(b)

    mask = (df['trend_short'] == 0) & (df['trend_long'] == 0) & (df['rsi'] < 50) & (df['rsi'] > 30)
    b = Behavior(
        "full_bear_alignment",
        "all EMAs bearish + RSI 30-50 (confirmed downtrend with room)",
        "next candle goes DOWN"
    )
    outcomes = (1 - df.loc[mask, 'next_dir']).values
    b.validate(
        outcomes, 1 - baseline_up,
        (1 - first.loc[first.index.isin(df[mask].index), 'next_dir']).values,
        (1 - second.loc[second.index.isin(df[mask].index), 'next_dir']).values
    )
    b.avg_return_after = df.loc[mask, 'next_ret'].mean()
    behaviors.append(b)

    # Vol squeeze + trend -> breakout
    mask = (df['vol_ratio'] < 0.6) & (df['trend_short'] == 1)
    b = Behavior(
        "squeeze_in_uptrend",
        "volatility squeeze + short-term uptrend",
        "breakout UP in next 5 candles"
    )
    outcomes = (df.loc[mask, 'next_5_ret'] > 0).astype(int).values
    b.validate(
        outcomes, 0.5,
        (first.loc[first.index.isin(df[mask].index), 'next_5_ret'] > 0).astype(int).values,
        (second.loc[second.index.isin(df[mask].index), 'next_5_ret'] > 0).astype(int).values
    )
    b.avg_return_after = df.loc[mask, 'next_5_ret'].mean()
    behaviors.append(b)

    mask = (df['vol_ratio'] < 0.6) & (df['trend_short'] == 0)
    b = Behavior(
        "squeeze_in_downtrend",
        "volatility squeeze + short-term downtrend",
        "breakout DOWN in next 5 candles"
    )
    outcomes = (df.loc[mask, 'next_5_ret'] < 0).astype(int).values
    b.validate(
        outcomes, 0.5,
        (first.loc[first.index.isin(df[mask].index), 'next_5_ret'] < 0).astype(int).values,
        (second.loc[second.index.isin(df[mask].index), 'next_5_ret'] < 0).astype(int).values
    )
    b.avg_return_after = df.loc[mask, 'next_5_ret'].mean()
    behaviors.append(b)

    return behaviors


# ============================================================
# MAIN: Run discovery on all timeframes
# ============================================================

def run_discovery(df_raw, symbol, timeframe):
    """Run full behavior discovery on a dataset"""
    print(f"\n{'#'*70}")
    print(f"#  BEHAVIOR DISCOVERY: {symbol} - {timeframe}")
    print(f"#  {len(df_raw)} candles | {(df_raw.index[-1] - df_raw.index[0]).days} days")
    print(f"{'#'*70}")

    # Prepare data
    df = prepare_data(df_raw)
    print(f"  Prepared: {len(df)} samples after feature computation")

    baseline_up = df['direction'].mean()
    print(f"  Baseline UP rate: {baseline_up*100:.1f}%")

    # Run all discovery modules
    all_behaviors = []

    print("\n  Scanning consecutive patterns...")
    all_behaviors.extend(discover_consecutive_behaviors(df, baseline_up))

    print("  Scanning volatility behaviors...")
    all_behaviors.extend(discover_volatility_behaviors(df, baseline_up))

    print("  Scanning spike behaviors...")
    all_behaviors.extend(discover_spike_behaviors(df, baseline_up))

    print("  Scanning RSI behaviors...")
    all_behaviors.extend(discover_rsi_behaviors(df, baseline_up))

    print("  Scanning trend structure behaviors...")
    all_behaviors.extend(discover_trend_structure_behaviors(df, baseline_up))

    print("  Scanning candle pattern behaviors...")
    all_behaviors.extend(discover_candle_pattern_behaviors(df, baseline_up))

    print("  Scanning time-based behaviors...")
    all_behaviors.extend(discover_time_behaviors(df, baseline_up))

    print("  Scanning combined behaviors...")
    all_behaviors.extend(discover_combined_behaviors(df, baseline_up))

    # Filter and sort
    valid = [b for b in all_behaviors if b.is_valid]
    invalid = [b for b in all_behaviors if not b.is_valid]

    valid.sort(key=lambda b: abs(b.edge), reverse=True)

    # Print results
    print(f"\n{'='*70}")
    print(f"  VALIDATED BEHAVIORS ({len(valid)} / {len(all_behaviors)} tested)")
    print(f"{'='*70}")

    if valid:
        for i, b in enumerate(valid, 1):
            print(f"\n  --- Behavior #{i} ---")
            print(f"  {b}")
            if b.details:
                for k, v in b.details.items():
                    if isinstance(v, float):
                        print(f"    {k}: {v:.6f}")
    else:
        print("\n  No statistically valid behaviors found on this timeframe.")

    # Summary table
    if valid:
        print(f"\n{'='*70}")
        print(f"  PLAYBOOK SUMMARY - {symbol} {timeframe}")
        print(f"{'='*70}")
        print(f"  {'#':<4} {'Behavior':<35} {'Edge':>7} {'Rate':>7} {'Base':>7} {'N':>5} {'p-val':>8} {'Consist':>10}")
        print(f"  {'-'*4} {'-'*35} {'-'*7} {'-'*7} {'-'*7} {'-'*5} {'-'*8} {'-'*10}")

        for i, b in enumerate(valid, 1):
            consist = f"{b.first_half_rate*100:.0f}/{b.second_half_rate*100:.0f}%"
            print(f"  {i:<4} {b.name:<35} {b.edge*100:>+6.1f}% {b.outcome_rate*100:>6.1f}% {b.baseline_rate*100:>6.1f}% {b.occurrences:>5} {b.p_value:>8.4f} {consist:>10}")

    return valid, invalid


def main():
    print("="*70)
    print("  BEHAVIOR DISCOVERY ENGINE")
    print("  Finding proven, repeated, validated market behaviors")
    print("="*70)

    symbol = "Crash 500 Index"
    timeframes = ['H1', 'H4', 'M15']

    all_valid = {}

    for tf in timeframes:
        fpath = Path(f'data/raw/Crash_500_Index_{tf}.parquet')
        if not fpath.exists():
            print(f"\n  SKIP {tf}: no data")
            continue

        df = pd.read_parquet(fpath)
        valid, invalid = run_discovery(df, symbol, tf)
        all_valid[tf] = valid

    # Cross-timeframe summary
    print(f"\n\n{'#'*70}")
    print(f"#  CROSS-TIMEFRAME SUMMARY")
    print(f"{'#'*70}")

    for tf, behaviors in all_valid.items():
        print(f"\n  {tf}: {len(behaviors)} validated behaviors")
        for b in behaviors[:5]:
            print(f"    [{b.edge*100:+.1f}%] {b.condition_desc} -> {b.outcome_desc}")

    # Find behaviors that appear across multiple timeframes
    print(f"\n{'='*70}")
    print(f"  MOST ROBUST (validated on multiple timeframes)")
    print(f"{'='*70}")

    behavior_names = {}
    for tf, behaviors in all_valid.items():
        for b in behaviors:
            base_name = b.name.split('_next_')[0] if '_next_' in b.name else b.name
            if base_name not in behavior_names:
                behavior_names[base_name] = []
            behavior_names[base_name].append((tf, b))

    multi_tf = {k: v for k, v in behavior_names.items() if len(v) > 1}
    if multi_tf:
        for name, entries in sorted(multi_tf.items(), key=lambda x: -len(x[1])):
            tfs = [e[0] for e in entries]
            edges = [e[1].edge * 100 for e in entries]
            print(f"\n  {name} (found on {', '.join(tfs)})")
            for tf, b in entries:
                print(f"    {tf}: edge={b.edge*100:+.1f}%, N={b.occurrences}, p={b.p_value:.4f}")
    else:
        print("\n  No behavior found across multiple timeframes.")

    print(f"\n{'='*70}")
    print(f"  DONE - Use these validated behaviors as trading rules")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
