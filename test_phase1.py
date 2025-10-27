#!/usr/bin/env python3
"""
Quick test script for Phase 1 components

Tests:
1. Massive data extraction (1 timeframe)
2. Advanced features calculation
3. Data retention after features

Usage:
    python test_phase1.py --symbol "Crash 500 Index" --timeframe H4
"""

import sys
import asyncio
from pathlib import Path
import pandas as pd
import argparse

# Add src to path
sys.path.append(str(Path.cwd()))

from extract_massive import MassiveExtractor
from src.features import calculate_all_advanced_features


async def test_extraction(symbol: str, timeframe: str, total_candles: int = 10000):
    """Test massive extraction"""
    print("="*70)
    print(" " * 20 + "TEST 1: MASSIVE EXTRACTION")
    print("="*70)

    extractor = MassiveExtractor()

    print(f"\nExtracting {total_candles} candles for {symbol} {timeframe}...")
    print("(This is a smaller test - full extraction will get 20,000 candles)\n")

    df = await extractor.extract_massive(
        symbol=symbol,
        timeframe=timeframe,
        total_candles=total_candles
    )

    if df is not None and len(df) > 0:
        print(f"\n✅ SUCCESS: Extracted {len(df)} candles")
        print(f"📅 Date range: {df.index[0]} to {df.index[-1]}")
        print(f"📊 Coverage: {(df.index[-1] - df.index[0]).days} days")
        return df
    else:
        print("\n❌ FAILED: No data extracted")
        return None


def test_advanced_features(df: pd.DataFrame):
    """Test advanced features calculation"""
    print("\n" + "="*70)
    print(" " * 20 + "TEST 2: ADVANCED FEATURES")
    print("="*70)

    print(f"\nBefore features: {len(df.columns)} columns")

    # Calculate advanced features
    df_enhanced = calculate_all_advanced_features(
        df,
        include_ichimoku=True,
        include_fibonacci=True,
        include_patterns=True,
        include_keltner=True,
        include_temporal=True,
        include_price_action=True
    )

    print(f"\nAfter features: {len(df_enhanced.columns)} columns")
    added = len(df_enhanced.columns) - len(df.columns)
    print(f"✅ Added {added} advanced features")

    # Check data retention
    before_dropna = len(df_enhanced)
    after_dropna = len(df_enhanced.dropna())
    retention = (after_dropna / before_dropna) * 100

    print(f"\n📊 Data Retention:")
    print(f"   Before dropna: {before_dropna} rows")
    print(f"   After dropna: {after_dropna} rows")
    print(f"   Retention: {retention:.1f}%")

    if retention < 90:
        print(f"   ⚠️  WARNING: Low retention! Use fillna() instead of dropna()")
    else:
        print(f"   ✅ Good retention")

    # Show some new features
    new_cols = [col for col in df_enhanced.columns if col not in df.columns]
    print(f"\n🎯 Sample of new features ({len(new_cols)} total):")
    for col in new_cols[:15]:
        print(f"   - {col}")

    if len(new_cols) > 15:
        print(f"   ... and {len(new_cols) - 15} more")

    return df_enhanced


def test_data_preparation(df: pd.DataFrame):
    """Test data preparation for LSTM"""
    print("\n" + "="*70)
    print(" " * 20 + "TEST 3: DATA PREPARATION")
    print("="*70)

    # Use fillna (as in improved notebook)
    df_clean = df.fillna(method='ffill').fillna(method='bfill').dropna()

    print(f"\nData after cleaning: {len(df_clean)} rows")

    # Simulate sequence creation
    sequence_length = 40
    num_sequences = max(0, len(df_clean) - sequence_length - 1 + 1)

    # Split ratios
    train_ratio = 0.7
    val_ratio = 0.15

    train_size = int(num_sequences * train_ratio)
    val_size = int(num_sequences * val_ratio)
    test_size = num_sequences - train_size - val_size

    print(f"\n📊 Sequence Statistics:")
    print(f"   Sequence length: {sequence_length}")
    print(f"   Total sequences: {num_sequences}")
    print(f"   Train sequences: {train_size} ({train_ratio*100:.0f}%)")
    print(f"   Val sequences: {val_size} ({val_ratio*100:.0f}%)")
    print(f"   Test sequences: {test_size} ({(1-train_ratio-val_ratio)*100:.0f}%)")

    if test_size < 300:
        print(f"\n   ⚠️  WARNING: Low test samples ({test_size})")
        print(f"      Recommendation: Extract more data (20,000 candles)")
    elif test_size < 500:
        print(f"\n   ⚠️  OK: Test samples = {test_size}")
        print(f"      Better with 20,000 candles (will give ~1500 test samples)")
    else:
        print(f"\n   ✅ GOOD: Test samples = {test_size}")

    return num_sequences


async def main():
    parser = argparse.ArgumentParser(description='Test Phase 1 components')
    parser.add_argument('--symbol', type=str, default='Crash 500 Index', help='Symbol to test')
    parser.add_argument('--timeframe', type=str, default='H4', help='Timeframe')
    parser.add_argument('--total-candles', type=int, default=10000, help='Candles to extract (test: 10000)')

    args = parser.parse_args()

    print("\n" + "="*70)
    print(" " * 15 + "PHASE 1 COMPONENT TEST")
    print("="*70)
    print(f"\nSymbol: {args.symbol}")
    print(f"Timeframe: {args.timeframe}")
    print(f"Test candles: {args.total_candles}")
    print(f"\nNote: This is a quick test with {args.total_candles} candles.")
    print(f"      Full extraction will use 20,000 candles per timeframe.")
    print("="*70 + "\n")

    # Test 1: Extraction
    df = await test_extraction(args.symbol, args.timeframe, args.total_candles)

    if df is None:
        print("\n❌ Extraction failed. Cannot continue tests.")
        return

    # Test 2: Advanced Features
    df_enhanced = test_advanced_features(df)

    # Test 3: Data Preparation
    num_sequences = test_data_preparation(df_enhanced)

    # Summary
    print("\n" + "="*70)
    print(" " * 25 + "TEST SUMMARY")
    print("="*70)
    print(f"\n✅ Test 1: Extraction - SUCCESS ({len(df)} candles)")
    print(f"✅ Test 2: Advanced Features - SUCCESS ({len(df_enhanced.columns)} total features)")
    print(f"✅ Test 3: Data Preparation - SUCCESS ({num_sequences} sequences)")

    print("\n" + "="*70)
    print(" " * 20 + "READY FOR PHASE 1!")
    print("="*70)
    print("\n🚀 Next Steps:")
    print("   1. Extract full dataset (20,000 candles):")
    print(f"      python extract_massive.py --symbol '{args.symbol}' --multi --total-candles 20000")
    print("\n   2. Run improved notebook:")
    print("      jupyter notebook notebooks/04_multi_timeframe_lstm.ipynb")
    print("\n   3. Check PHASE1_QUICK_START.md for detailed instructions")
    print("="*70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
