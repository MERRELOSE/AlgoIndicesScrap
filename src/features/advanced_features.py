"""
Advanced Feature Engineering Module

Provides sophisticated technical indicators and pattern detection:
- Ichimoku Cloud
- Fibonacci Retracements
- Candlestick Patterns
- Keltner Channels
- Temporal Features
- Price Action Patterns
"""

import pandas as pd
import numpy as np
from typing import Tuple, Dict


def calculate_ichimoku(df: pd.DataFrame,
                       conversion_period: int = 9,
                       base_period: int = 26,
                       span_b_period: int = 52,
                       displacement: int = 26) -> pd.DataFrame:
    """
    Calculate Ichimoku Cloud indicator

    Components:
    - Tenkan-sen (Conversion Line): (9-period high + 9-period low)/2
    - Kijun-sen (Base Line): (26-period high + 26-period low)/2
    - Senkou Span A (Leading Span A): (Conversion + Base)/2, plotted 26 periods ahead
    - Senkou Span B (Leading Span B): (52-period high + 52-period low)/2, plotted 26 periods ahead
    - Chikou Span (Lagging Span): Close plotted 26 periods back

    Args:
        df: DataFrame with OHLC data
        conversion_period: Tenkan-sen period (default: 9)
        base_period: Kijun-sen period (default: 26)
        span_b_period: Senkou Span B period (default: 52)
        displacement: Forward displacement for spans (default: 26)

    Returns:
        DataFrame with Ichimoku components added
    """
    df = df.copy()

    # Tenkan-sen (Conversion Line): (9-period high + 9-period low)/2
    high_9 = df['High'].rolling(window=conversion_period).max()
    low_9 = df['Low'].rolling(window=conversion_period).min()
    df['Ichimoku_Conversion'] = (high_9 + low_9) / 2

    # Kijun-sen (Base Line): (26-period high + 26-period low)/2
    high_26 = df['High'].rolling(window=base_period).max()
    low_26 = df['Low'].rolling(window=base_period).min()
    df['Ichimoku_Base'] = (high_26 + low_26) / 2

    # Senkou Span A (Leading Span A): (Conversion + Base)/2, displaced forward
    df['Ichimoku_SpanA'] = ((df['Ichimoku_Conversion'] + df['Ichimoku_Base']) / 2).shift(displacement)

    # Senkou Span B (Leading Span B): (52-period high + 52-period low)/2, displaced forward
    high_52 = df['High'].rolling(window=span_b_period).max()
    low_52 = df['Low'].rolling(window=span_b_period).min()
    df['Ichimoku_SpanB'] = ((high_52 + low_52) / 2).shift(displacement)

    # Chikou Span (Lagging Span): Close displaced backward
    df['Ichimoku_Lagging'] = df['Close'].shift(-displacement)

    # Cloud thickness (difference between spans)
    df['Ichimoku_Cloud_Thickness'] = abs(df['Ichimoku_SpanA'] - df['Ichimoku_SpanB'])

    # Price position relative to cloud
    df['Ichimoku_Price_Above_Cloud'] = (
        (df['Close'] > df['Ichimoku_SpanA']) &
        (df['Close'] > df['Ichimoku_SpanB'])
    ).astype(int)

    df['Ichimoku_Price_Below_Cloud'] = (
        (df['Close'] < df['Ichimoku_SpanA']) &
        (df['Close'] < df['Ichimoku_SpanB'])
    ).astype(int)

    df['Ichimoku_Price_In_Cloud'] = (
        ~df['Ichimoku_Price_Above_Cloud'].astype(bool) &
        ~df['Ichimoku_Price_Below_Cloud'].astype(bool)
    ).astype(int)

    return df


def calculate_fibonacci_levels(df: pd.DataFrame, period: int = 100) -> pd.DataFrame:
    """
    Calculate Fibonacci retracement levels

    Based on recent high/low over specified period:
    - 0.236 (23.6%)
    - 0.382 (38.2%)
    - 0.500 (50.0%)
    - 0.618 (61.8%)
    - 0.786 (78.6%)

    Args:
        df: DataFrame with OHLC data
        period: Lookback period for high/low (default: 100)

    Returns:
        DataFrame with Fibonacci levels added
    """
    df = df.copy()

    # Calculate recent high and low
    recent_high = df['High'].rolling(window=period).max()
    recent_low = df['Low'].rolling(window=period).min()
    diff = recent_high - recent_low

    # Fibonacci retracement levels
    df['Fib_0_236'] = recent_low + 0.236 * diff
    df['Fib_0_382'] = recent_low + 0.382 * diff
    df['Fib_0_500'] = recent_low + 0.500 * diff
    df['Fib_0_618'] = recent_low + 0.618 * diff
    df['Fib_0_786'] = recent_low + 0.786 * diff

    # Distance of current price from each Fibonacci level (normalized)
    for level in [0.236, 0.382, 0.500, 0.618, 0.786]:
        level_name = str(level).replace('.', '_')
        fib_col = f'Fib_{level_name}'
        df[f'Fib_Dist_{level_name}'] = (df['Close'] - df[fib_col]) / diff

    # Which Fibonacci zone is price in?
    df['Fib_Zone'] = 0  # Below 0.236
    df.loc[df['Close'] >= df['Fib_0_236'], 'Fib_Zone'] = 1
    df.loc[df['Close'] >= df['Fib_0_382'], 'Fib_Zone'] = 2
    df.loc[df['Close'] >= df['Fib_0_500'], 'Fib_Zone'] = 3
    df.loc[df['Close'] >= df['Fib_0_618'], 'Fib_Zone'] = 4
    df.loc[df['Close'] >= df['Fib_0_786'], 'Fib_Zone'] = 5
    df.loc[df['Close'] >= recent_high, 'Fib_Zone'] = 6  # Above high

    return df


def detect_candlestick_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect common candlestick patterns

    Patterns detected:
    - Doji: Open ≈ Close (small body)
    - Hammer: Long lower shadow, small upper shadow
    - Shooting Star: Long upper shadow, small lower shadow
    - Engulfing (Bullish/Bearish)
    - Morning/Evening Star
    - Three White Soldiers / Three Black Crows

    Args:
        df: DataFrame with OHLC data

    Returns:
        DataFrame with pattern indicators added
    """
    df = df.copy()

    # Calculate body and shadow sizes
    body = abs(df['Close'] - df['Open'])
    total_range = df['High'] - df['Low']
    upper_shadow = df['High'] - df[['Open', 'Close']].max(axis=1)
    lower_shadow = df[['Open', 'Close']].min(axis=1) - df['Low']

    # Avoid division by zero
    total_range = total_range.replace(0, np.nan)

    # 1. Doji: Body is less than 10% of total range
    df['Pattern_Doji'] = (body / total_range < 0.1).astype(int)

    # 2. Hammer: Lower shadow > 2x body, upper shadow small
    df['Pattern_Hammer'] = (
        (lower_shadow > 2 * body) &
        (upper_shadow < 0.5 * body)
    ).astype(int)

    # 3. Shooting Star: Upper shadow > 2x body, lower shadow small
    df['Pattern_Shooting_Star'] = (
        (upper_shadow > 2 * body) &
        (lower_shadow < 0.5 * body)
    ).astype(int)

    # 4. Bullish Engulfing
    prev_bearish = df['Close'].shift(1) < df['Open'].shift(1)
    curr_bullish = df['Close'] > df['Open']
    curr_engulfs = (df['Open'] < df['Close'].shift(1)) & (df['Close'] > df['Open'].shift(1))
    df['Pattern_Bullish_Engulfing'] = (prev_bearish & curr_bullish & curr_engulfs).astype(int)

    # 5. Bearish Engulfing
    prev_bullish = df['Close'].shift(1) > df['Open'].shift(1)
    curr_bearish = df['Close'] < df['Open']
    curr_engulfs = (df['Open'] > df['Close'].shift(1)) & (df['Close'] < df['Open'].shift(1))
    df['Pattern_Bearish_Engulfing'] = (prev_bullish & curr_bearish & curr_engulfs).astype(int)

    # 6. Three White Soldiers: 3 consecutive bullish candles with higher closes
    three_bullish = (
        (df['Close'] > df['Open']) &
        (df['Close'].shift(1) > df['Open'].shift(1)) &
        (df['Close'].shift(2) > df['Open'].shift(2))
    )
    higher_closes = (
        (df['Close'] > df['Close'].shift(1)) &
        (df['Close'].shift(1) > df['Close'].shift(2))
    )
    df['Pattern_Three_White_Soldiers'] = (three_bullish & higher_closes).astype(int)

    # 7. Three Black Crows: 3 consecutive bearish candles with lower closes
    three_bearish = (
        (df['Close'] < df['Open']) &
        (df['Close'].shift(1) < df['Open'].shift(1)) &
        (df['Close'].shift(2) < df['Open'].shift(2))
    )
    lower_closes = (
        (df['Close'] < df['Close'].shift(1)) &
        (df['Close'].shift(1) < df['Close'].shift(2))
    )
    df['Pattern_Three_Black_Crows'] = (three_bearish & lower_closes).astype(int)

    return df


def calculate_keltner_channels(df: pd.DataFrame,
                               ema_period: int = 20,
                               atr_period: int = 14,
                               multiplier: float = 2.0) -> pd.DataFrame:
    """
    Calculate Keltner Channels

    Components:
    - Middle Line: EMA(20)
    - Upper Channel: EMA + (multiplier × ATR)
    - Lower Channel: EMA - (multiplier × ATR)

    Args:
        df: DataFrame with OHLC data
        ema_period: EMA period (default: 20)
        atr_period: ATR period (default: 14)
        multiplier: ATR multiplier (default: 2.0)

    Returns:
        DataFrame with Keltner Channels added
    """
    df = df.copy()

    # Middle line: EMA
    df['Keltner_Middle'] = df['Close'].ewm(span=ema_period, adjust=False).mean()

    # ATR calculation
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    atr = true_range.rolling(atr_period).mean()

    # Upper and lower channels
    df['Keltner_Upper'] = df['Keltner_Middle'] + (multiplier * atr)
    df['Keltner_Lower'] = df['Keltner_Middle'] - (multiplier * atr)

    # Channel width
    df['Keltner_Width'] = df['Keltner_Upper'] - df['Keltner_Lower']

    # Price position relative to channels
    df['Keltner_Position'] = (df['Close'] - df['Keltner_Lower']) / df['Keltner_Width']

    return df


def calculate_temporal_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate temporal (time-based) features

    Features:
    - Hour of day (0-23)
    - Day of week (0-6)
    - Cyclical encoding (sin/cos) for periodicity
    - Is market session (assuming 24/7 for synthetic indices)

    Args:
        df: DataFrame with datetime index

    Returns:
        DataFrame with temporal features added
    """
    df = df.copy()

    # Extract time components
    df['Hour'] = df.index.hour
    df['DayOfWeek'] = df.index.dayofweek
    df['DayOfMonth'] = df.index.day
    df['Month'] = df.index.month

    # Cyclical encoding for hour (24-hour cycle)
    df['Hour_Sin'] = np.sin(2 * np.pi * df['Hour'] / 24)
    df['Hour_Cos'] = np.cos(2 * np.pi * df['Hour'] / 24)

    # Cyclical encoding for day of week (7-day cycle)
    df['DayOfWeek_Sin'] = np.sin(2 * np.pi * df['DayOfWeek'] / 7)
    df['DayOfWeek_Cos'] = np.cos(2 * np.pi * df['DayOfWeek'] / 7)

    # Is weekend? (Saturday=5, Sunday=6)
    df['Is_Weekend'] = (df['DayOfWeek'] >= 5).astype(int)

    # Trading sessions (for synthetic indices, 24/7, but can define sessions)
    # Example: Asian (0-8), European (8-16), American (16-24)
    df['Session_Asian'] = ((df['Hour'] >= 0) & (df['Hour'] < 8)).astype(int)
    df['Session_European'] = ((df['Hour'] >= 8) & (df['Hour'] < 16)).astype(int)
    df['Session_American'] = ((df['Hour'] >= 16) & (df['Hour'] < 24)).astype(int)

    return df


def calculate_price_action_features(df: pd.DataFrame, periods: list = [5, 10, 20]) -> pd.DataFrame:
    """
    Calculate price action features

    Features:
    - Higher highs / Lower lows
    - Support / Resistance touches
    - Price momentum
    - Range expansion/contraction

    Args:
        df: DataFrame with OHLC data
        periods: List of lookback periods (default: [5, 10, 20])

    Returns:
        DataFrame with price action features added
    """
    df = df.copy()

    for period in periods:
        # Higher Highs
        df[f'Higher_High_{period}'] = (df['High'] > df['High'].shift(1).rolling(period).max()).astype(int)

        # Lower Lows
        df[f'Lower_Low_{period}'] = (df['Low'] < df['Low'].shift(1).rolling(period).min()).astype(int)

        # Support level (recent low)
        support = df['Low'].rolling(period).min()
        df[f'Support_{period}'] = support
        df[f'Dist_To_Support_{period}'] = (df['Close'] - support) / df['Close']

        # Resistance level (recent high)
        resistance = df['High'].rolling(period).max()
        df[f'Resistance_{period}'] = resistance
        df[f'Dist_To_Resistance_{period}'] = (resistance - df['Close']) / df['Close']

        # Range (high - low over period)
        df[f'Range_{period}'] = df['High'].rolling(period).max() - df['Low'].rolling(period).min()

        # Is range expanding?
        df[f'Range_Expanding_{period}'] = (
            df[f'Range_{period}'] > df[f'Range_{period}'].shift(period)
        ).astype(int)

    # Consecutive up/down candles
    df['Consecutive_Up'] = 0
    df['Consecutive_Down'] = 0

    up_streak = 0
    down_streak = 0
    consecutive_up = []
    consecutive_down = []

    for i in range(len(df)):
        if i == 0:
            consecutive_up.append(0)
            consecutive_down.append(0)
            continue

        if df['Close'].iloc[i] > df['Close'].iloc[i-1]:
            up_streak += 1
            down_streak = 0
        elif df['Close'].iloc[i] < df['Close'].iloc[i-1]:
            down_streak += 1
            up_streak = 0
        else:
            up_streak = 0
            down_streak = 0

        consecutive_up.append(up_streak)
        consecutive_down.append(down_streak)

    df['Consecutive_Up'] = consecutive_up
    df['Consecutive_Down'] = consecutive_down

    return df


def calculate_all_advanced_features(df: pd.DataFrame,
                                    include_ichimoku: bool = True,
                                    include_fibonacci: bool = True,
                                    include_patterns: bool = True,
                                    include_keltner: bool = True,
                                    include_temporal: bool = True,
                                    include_price_action: bool = True) -> pd.DataFrame:
    """
    Calculate all advanced features at once

    Args:
        df: DataFrame with OHLC data
        include_ichimoku: Include Ichimoku Cloud (default: True)
        include_fibonacci: Include Fibonacci levels (default: True)
        include_patterns: Include candlestick patterns (default: True)
        include_keltner: Include Keltner Channels (default: True)
        include_temporal: Include temporal features (default: True)
        include_price_action: Include price action features (default: True)

    Returns:
        DataFrame with all selected advanced features
    """
    df = df.copy()

    initial_cols = len(df.columns)

    if include_ichimoku:
        df = calculate_ichimoku(df)

    if include_fibonacci:
        df = calculate_fibonacci_levels(df)

    if include_patterns:
        df = detect_candlestick_patterns(df)

    if include_keltner:
        df = calculate_keltner_channels(df)

    if include_temporal:
        df = calculate_temporal_features(df)

    if include_price_action:
        df = calculate_price_action_features(df)

    final_cols = len(df.columns)
    added_features = final_cols - initial_cols

    print(f"✅ Added {added_features} advanced features")
    print(f"   Total features: {final_cols}")

    return df
