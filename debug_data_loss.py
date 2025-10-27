#!/usr/bin/env python3
"""
Script de diagnostic pour identifier où les données sont perdues
"""
import sys
import pandas as pd
import numpy as np
from pathlib import Path

# Add src to path
sys.path.append(str(Path.cwd()))

from src.utils.helpers import load_data

def calculate_indicators(df, prefix=''):
    """Calculate technical indicators (same as notebook)"""
    df = df.copy()

    print(f"  [{prefix}] Before indicators: {len(df)} rows")

    # Returns
    df[f'{prefix}Returns'] = df['Close'].pct_change()

    # Simple Moving Averages
    df[f'{prefix}SMA_10'] = df['Close'].rolling(window=10).mean()
    df[f'{prefix}SMA_20'] = df['Close'].rolling(window=20).mean()
    df[f'{prefix}SMA_50'] = df['Close'].rolling(window=50).mean()

    # Exponential Moving Averages
    df[f'{prefix}EMA_10'] = df['Close'].ewm(span=10, adjust=False).mean()
    df[f'{prefix}EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()

    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df[f'{prefix}RSI'] = 100 - (100 / (1 + rs))

    # MACD
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df[f'{prefix}MACD'] = exp1 - exp2
    df[f'{prefix}MACD_signal'] = df[f'{prefix}MACD'].ewm(span=9, adjust=False).mean()

    # Bollinger Bands
    df[f'{prefix}BB_middle'] = df['Close'].rolling(window=20).mean()
    bb_std = df['Close'].rolling(window=20).std()
    df[f'{prefix}BB_upper'] = df[f'{prefix}BB_middle'] + (bb_std * 2)
    df[f'{prefix}BB_lower'] = df[f'{prefix}BB_middle'] - (bb_std * 2)
    df[f'{prefix}BB_width'] = df[f'{prefix}BB_upper'] - df[f'{prefix}BB_lower']

    # ATR
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df[f'{prefix}ATR'] = true_range.rolling(14).mean()

    # Volatility
    df[f'{prefix}Volatility'] = df['Close'].rolling(window=20).std()

    print(f"  [{prefix}] After indicators: {len(df)} rows")
    print(f"  [{prefix}] NaN count: {df.isna().sum().sum()}")

    return df


def align_multi_timeframe(data_dict, target_timeframe):
    """Align timeframes (same as notebook)"""
    print(f"\n📊 ALIGNING TIMEFRAMES (target: {target_timeframe})")

    df_target = data_dict[target_timeframe].copy()
    print(f"  Target ({target_timeframe}) before alignment: {len(df_target)} rows")

    # Remove prefix from target
    target_prefix = f'{target_timeframe}_'
    df_target.columns = [col.replace(target_prefix, '') for col in df_target.columns]

    # Select features
    target_features = ['Close', 'Returns', 'SMA_10', 'SMA_20', 'EMA_10',
                      'RSI', 'MACD', 'BB_middle', 'BB_width', 'ATR', 'Volatility']
    target_features = [f for f in target_features if f in df_target.columns]
    df_aligned = df_target[target_features].copy()

    print(f"  After selecting target features: {len(df_aligned)} rows")

    # Merge other timeframes
    for tf in data_dict.keys():
        if tf == target_timeframe:
            continue

        df_tf = data_dict[tf].copy()
        tf_prefix = f'{tf}_'

        selected_features = [
            f'{tf_prefix}Close', f'{tf_prefix}Returns', f'{tf_prefix}SMA_10',
            f'{tf_prefix}RSI', f'{tf_prefix}MACD', f'{tf_prefix}Volatility'
        ]
        selected_features = [f for f in selected_features if f in df_tf.columns]
        df_tf_selected = df_tf[selected_features]

        print(f"  Merging {tf}: {len(df_tf_selected)} rows")

        df_aligned = pd.merge_asof(
            df_aligned.sort_index(),
            df_tf_selected.sort_index(),
            left_index=True,
            right_index=True,
            direction='backward'
        )

        print(f"  After merge with {tf}: {len(df_aligned)} rows")

    # Drop NaN
    print(f"  Before dropna(): {len(df_aligned)} rows, NaN: {df_aligned.isna().sum().sum()}")
    df_aligned = df_aligned.dropna()
    print(f"  ⚠️  After dropna(): {len(df_aligned)} rows (LOST: {len(df_target) - len(df_aligned)} rows)")

    return df_aligned


def analyze_sequences(df_aligned, sequence_length=60, train_ratio=0.7, val_ratio=0.15):
    """Analyze sequence creation"""
    print(f"\n🔢 SEQUENCE CREATION (seq_len={sequence_length})")

    print(f"  Before sequences: {len(df_aligned)} rows")

    # Calculate number of sequences
    num_sequences = len(df_aligned) - sequence_length - 1 + 1
    print(f"  Number of sequences: {num_sequences}")

    if num_sequences <= 0:
        print(f"  ❌ ERROR: Not enough data for sequences!")
        return

    # Split
    train_size = int(num_sequences * train_ratio)
    val_size = int(num_sequences * val_ratio)
    test_size = num_sequences - train_size - val_size

    print(f"\n📊 SPLIT:")
    print(f"  Train: {train_size} sequences ({train_ratio*100:.0f}%)")
    print(f"  Val: {val_size} sequences ({val_ratio*100:.0f}%)")
    print(f"  Test: {test_size} sequences ({(1-train_ratio-val_ratio)*100:.0f}%)")
    print(f"  Total: {num_sequences} sequences")


def main():
    SYMBOL = 'Crash 500 Index'
    TIMEFRAMES = ['M15', 'H1', 'H4']
    TARGET_TIMEFRAME = 'H4'
    SEQUENCE_LENGTH = 60

    print("="*70)
    print(" " * 20 + "DATA LOSS DIAGNOSTIC")
    print("="*70)
    print(f"\nSymbol: {SYMBOL}")
    print(f"Timeframes: {', '.join(TIMEFRAMES)}")
    print(f"Target: {TARGET_TIMEFRAME}")

    # Load data
    print(f"\n📥 LOADING DATA:")
    data_dict = {}

    for tf in TIMEFRAMES:
        df = load_data(SYMBOL, tf)
        if df is None:
            print(f"  ❌ Failed to load {tf}")
            return
        data_dict[tf] = df
        print(f"  ✅ {tf}: {len(df)} rows ({df.index[0]} to {df.index[-1]})")

    # Calculate indicators
    print(f"\n🧮 CALCULATING INDICATORS:")
    for tf in TIMEFRAMES:
        prefix = f'{tf}_'
        data_dict[tf] = calculate_indicators(data_dict[tf], prefix=prefix)

    # Align
    df_aligned = align_multi_timeframe(data_dict, TARGET_TIMEFRAME)

    # Analyze sequences
    analyze_sequences(df_aligned, SEQUENCE_LENGTH)

    # Summary
    print("\n" + "="*70)
    print(" " * 25 + "SUMMARY")
    print("="*70)
    print(f"Original H4 data: {len(data_dict['H4'])} candles")
    print(f"After alignment: {len(df_aligned)} rows")
    print(f"Data loss: {len(data_dict['H4']) - len(df_aligned)} rows ({(1 - len(df_aligned)/len(data_dict['H4']))*100:.1f}%)")

    num_sequences = max(0, len(df_aligned) - SEQUENCE_LENGTH)
    test_size = int(num_sequences * 0.15)
    print(f"\nFinal test samples: {test_size}")

    print("\n" + "="*70)
    print("\n💡 RECOMMENDATIONS:")
    print("  1. Reduce indicator windows (SMA_10 instead of SMA_50)")
    print("  2. Use fillna(method='ffill') instead of dropna()")
    print("  3. Extract more historical data (multiple API calls)")
    print("  4. Reduce SEQUENCE_LENGTH (try 30 instead of 60)")
    print("="*70)


if __name__ == "__main__":
    main()
