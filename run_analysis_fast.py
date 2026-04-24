#!/usr/bin/env python3
"""
Fast analysis - uses already extracted M15/H1, extracts H4, then runs full stats
"""
import asyncio
import sys
from pathlib import Path
sys.path.append(str(Path.cwd()))

import pandas as pd
import numpy as np

# Import analysis functions from main script
from run_analysis import (
    extract_symbol, compute_returns, analyze_distribution,
    analyze_autocorrelation, analyze_hurst, analyze_stationarity,
    detect_spikes, analyze_temporal_patterns, analyze_volatility_clustering,
    compute_entropy, analyze_consecutive_patterns, print_report
)
from loguru import logger


async def main():
    Path('logs').mkdir(exist_ok=True)
    Path('data/raw').mkdir(parents=True, exist_ok=True)
    logger.add("logs/analysis.log", rotation="50 MB")

    datasets = {}

    # Load existing data
    for tf in ['M15', 'H1']:
        fpath = Path(f'data/raw/Crash_500_Index_{tf}.parquet')
        if fpath.exists():
            datasets[tf] = pd.read_parquet(fpath)
            print(f"Loaded {tf}: {len(datasets[tf])} candles")

    # Extract H4 (small - ~2191 candles max)
    print("\nExtracting H4...")
    df_h4 = await extract_symbol('Crash 500 Index', 'H4', 3000)
    if df_h4 is not None:
        df_h4.to_parquet('data/raw/Crash_500_Index_H4.parquet', compression='snappy')
        datasets['H4'] = df_h4
        print(f"Extracted H4: {len(df_h4)} candles")

    # Run analysis on each timeframe
    all_signals = {}

    for tf, df in datasets.items():
        print(f"\n{'#'*70}")
        print(f"# ANALYSE: Crash 500 Index - {tf} ({len(df)} candles)")
        print(f"{'#'*70}")

        df = compute_returns(df)

        results = {}
        results['distribution'] = analyze_distribution(df['returns'])
        results['autocorrelation'] = analyze_autocorrelation(df['returns'])
        results['hurst'] = analyze_hurst(df['returns'].values)
        results['stationarity'] = analyze_stationarity(df['returns'])
        results['spikes'], crash_df, boom_df = detect_spikes(df)
        results['temporal'] = analyze_temporal_patterns(df)
        results['volatility_clustering'] = analyze_volatility_clustering(df['returns'])
        results['entropy'] = compute_entropy(df['returns'].values)
        results['consecutive'] = analyze_consecutive_patterns(df)

        signals = print_report('Crash 500 Index', tf, df, results)
        all_signals[tf] = signals

    # Final summary
    print("\n\n" + "#"*70)
    print("#" + " "*20 + "RESUME GLOBAL" + " "*20 + "#")
    print("#"*70)

    for tf, signals in all_signals.items():
        print(f"\n  {tf}: {len(signals)} signal(s)")
        for s in signals:
            print(f"    - {s}")

    print("\n" + "#"*70)


if __name__ == "__main__":
    asyncio.run(main())
