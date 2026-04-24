#!/usr/bin/env python3
"""
FULL INDEX SCANNER
==================
Extract data + run behavior discovery on ALL Deriv synthetic indices.
Output: ranking of which indices have the most exploitable behaviors.

This helps us CHOOSE where to focus our efforts.
"""

import asyncio
import json
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import websockets
from loguru import logger
import warnings
warnings.filterwarnings('ignore')

# Import our existing tools
from run_analysis import extract_symbol, SYMBOL_MAP
from behavior_discovery import prepare_data, Behavior, run_discovery


# ============================================================
# EXTRACTION: All indices, H1 timeframe (best balance of data/signal)
# ============================================================

ALL_INDICES = [
    # Crash/Boom - spike-based
    'Crash 500 Index',
    'Crash 1000 Index',
    'Boom 500 Index',
    'Boom 1000 Index',
    # Volatility - continuous
    'Volatility 10 Index',
    'Volatility 25 Index',
    'Volatility 50 Index',
    'Volatility 75 Index',
    'Volatility 100 Index',
    # Step
    'Step Index',
]


async def extract_all_indices(timeframe='H1', target=5000):
    """Extract data for all indices"""
    output_dir = Path('data/raw')
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    for symbol in ALL_INDICES:
        safe_name = symbol.replace(' ', '_')
        fpath = output_dir / f"{safe_name}_{timeframe}.parquet"

        # Skip if already extracted
        if fpath.exists():
            df = pd.read_parquet(fpath)
            if len(df) > 1000:
                print(f"  CACHED: {symbol} ({len(df)} candles)")
                results[symbol] = df
                continue

        print(f"\n  Extracting {symbol} ({timeframe})...")
        try:
            df = await extract_symbol(symbol, timeframe, target)
            if df is not None and len(df) > 500:
                df.to_parquet(fpath, compression='snappy')
                results[symbol] = df
                print(f"  OK: {len(df)} candles | {(df.index[-1] - df.index[0]).days} days")
            else:
                print(f"  FAIL: not enough data")
        except Exception as e:
            print(f"  ERROR: {e}")

        # Cooldown between symbols
        await asyncio.sleep(2)

    return results


# ============================================================
# QUICK STATISTICAL PROFILE for each index
# ============================================================

def quick_profile(df, symbol):
    """Quick statistical profile of an index"""
    df = df.copy()
    df['ret'] = df['Close'].pct_change()
    df = df.dropna()

    ret = df['ret']

    profile = {
        'symbol': symbol,
        'candles': len(df),
        'days': (df.index[-1] - df.index[0]).days,
        'mean_return': ret.mean(),
        'std_return': ret.std(),
        'skewness': ret.skew(),
        'kurtosis': ret.kurt(),
        'pct_up': (ret > 0).mean(),
    }

    # Hurst exponent (quick version)
    lags = range(2, min(50, len(ret) // 10))
    rs_values = []
    for lag in lags:
        n = len(ret)
        num_sub = n // lag
        rs_sub = []
        for i in range(min(num_sub, 50)):
            sub = ret.values[i*lag:(i+1)*lag]
            if len(sub) < 2:
                continue
            m = sub.mean()
            dev = sub - m
            cum = np.cumsum(dev)
            R = cum.max() - cum.min()
            S = sub.std(ddof=1)
            if S > 0:
                rs_sub.append(R / S)
        if rs_sub:
            rs_values.append(np.mean(rs_sub))

    valid_lags = list(lags)[:len(rs_values)]
    if len(valid_lags) > 5:
        slope, _ = np.polyfit(np.log(valid_lags), np.log(rs_values), 1)
        profile['hurst'] = slope
    else:
        profile['hurst'] = 0.5

    # Spike detection
    std3 = ret.mean() - 3 * ret.std()
    std3_up = ret.mean() + 3 * ret.std()
    profile['crash_spikes'] = (ret < std3).sum()
    profile['boom_spikes'] = (ret > std3_up).sum()

    # Autocorrelation lag-1
    if len(ret) > 100:
        profile['autocorr_1'] = ret.autocorr(lag=1)
        profile['autocorr_5'] = ret.autocorr(lag=5)
        profile['abs_autocorr_1'] = ret.abs().autocorr(lag=1)
    else:
        profile['autocorr_1'] = 0
        profile['autocorr_5'] = 0
        profile['abs_autocorr_1'] = 0

    # Regime: what kind of index is this?
    if profile['hurst'] > 0.55:
        profile['regime'] = 'TRENDING'
    elif profile['hurst'] < 0.45:
        profile['regime'] = 'MEAN_REVERT'
    else:
        profile['regime'] = 'RANDOM'

    return profile


# ============================================================
# SCORING: Which index is most exploitable?
# ============================================================

def score_index(profile, n_behaviors):
    """
    Score an index on how exploitable it is.
    Higher = better for trading.
    """
    score = 0

    # 1. Hurst away from 0.5 (trending or mean-reverting = exploitable)
    hurst_edge = abs(profile['hurst'] - 0.5)
    score += hurst_edge * 100  # max ~15 points

    # 2. Number of valid behaviors found
    score += n_behaviors * 5  # each behavior = 5 points

    # 3. Autocorrelation (predictability)
    score += abs(profile.get('autocorr_1', 0)) * 50
    score += abs(profile.get('abs_autocorr_1', 0)) * 30  # vol clustering

    # 4. Kurtosis (fat tails = opportunity from spikes)
    score += min(profile['kurtosis'], 10) * 2

    # 5. Enough data
    if profile['candles'] < 2000:
        score *= 0.7  # penalty for small dataset

    # 6. High skew = directional bias = exploitable
    score += abs(profile['skewness']) * 10

    return round(score, 1)


# ============================================================
# MAIN
# ============================================================

async def main():
    print("="*70)
    print("  FULL INDEX SCANNER - Finding the best indices to trade")
    print("="*70)

    Path('logs').mkdir(exist_ok=True)
    logger.add("logs/scan.log", rotation="50 MB", level="WARNING")

    # Step 1: Extract all indices
    print("\n--- STEP 1: EXTRACTING DATA ---")
    datasets = await extract_all_indices(timeframe='H1', target=8000)

    print(f"\n  Extracted {len(datasets)} / {len(ALL_INDICES)} indices")

    # Step 2: Quick profiles
    print(f"\n--- STEP 2: STATISTICAL PROFILES ---")
    profiles = {}
    for symbol, df in datasets.items():
        profiles[symbol] = quick_profile(df, symbol)

    # Print profiles table
    print(f"\n  {'Symbol':<25} {'Candles':>7} {'Days':>5} {'Hurst':>6} {'Skew':>7} {'Kurt':>7} {'%UP':>5} {'Regime':<12} {'AC1':>6} {'|AC1|':>6}")
    print(f"  {'-'*25} {'-'*7} {'-'*5} {'-'*6} {'-'*7} {'-'*7} {'-'*5} {'-'*12} {'-'*6} {'-'*6}")

    for sym in ALL_INDICES:
        if sym in profiles:
            p = profiles[sym]
            print(f"  {p['symbol']:<25} {p['candles']:>7} {p['days']:>5} {p['hurst']:>6.3f} {p['skewness']:>+7.3f} {p['kurtosis']:>7.2f} {p['pct_up']*100:>4.1f}% {p['regime']:<12} {p['autocorr_1']:>+6.3f} {p['abs_autocorr_1']:>6.3f}")

    # Step 3: Run behavior discovery on each index
    print(f"\n--- STEP 3: BEHAVIOR DISCOVERY ---")
    behavior_counts = {}

    for symbol, df in datasets.items():
        print(f"\n  Scanning {symbol}...")
        try:
            valid, invalid = run_discovery(df, symbol, 'H1')
            behavior_counts[symbol] = {
                'valid': len(valid),
                'total': len(valid) + len(invalid),
                'behaviors': valid,
                'top_edge': max([abs(b.edge) for b in valid]) if valid else 0,
                'top_behavior': valid[0].name if valid else 'none',
            }
        except Exception as e:
            print(f"  ERROR: {e}")
            behavior_counts[symbol] = {'valid': 0, 'total': 0, 'behaviors': [], 'top_edge': 0, 'top_behavior': 'error'}

    # Step 4: Final scoring and ranking
    print(f"\n\n{'#'*70}")
    print(f"#  FINAL RANKING - Which index to trade?")
    print(f"{'#'*70}")

    rankings = []
    for symbol in ALL_INDICES:
        if symbol in profiles and symbol in behavior_counts:
            p = profiles[symbol]
            bc = behavior_counts[symbol]
            score = score_index(p, bc['valid'])
            rankings.append({
                'symbol': symbol,
                'score': score,
                'hurst': p['hurst'],
                'regime': p['regime'],
                'behaviors': bc['valid'],
                'top_edge': bc['top_edge'],
                'top_behavior': bc['top_behavior'],
                'skewness': p['skewness'],
                'autocorr': p['autocorr_1'],
                'vol_cluster': p['abs_autocorr_1'],
                'candles': p['candles'],
            })

    rankings.sort(key=lambda x: x['score'], reverse=True)

    print(f"\n  {'Rank':<5} {'Symbol':<25} {'Score':>6} {'Hurst':>6} {'Regime':<12} {'Behaviors':>10} {'TopEdge':>8} {'Skew':>7} {'VolClust':>8}")
    print(f"  {'-'*5} {'-'*25} {'-'*6} {'-'*6} {'-'*12} {'-'*10} {'-'*8} {'-'*7} {'-'*8}")

    for i, r in enumerate(rankings, 1):
        marker = " <<<" if i <= 3 else ""
        print(f"  {i:<5} {r['symbol']:<25} {r['score']:>6.1f} {r['hurst']:>6.3f} {r['regime']:<12} {r['behaviors']:>10} {r['top_edge']*100:>+7.1f}% {r['skewness']:>+7.3f} {r['vol_cluster']:>8.3f}{marker}")

    # Top 3 detailed
    print(f"\n{'='*70}")
    print(f"  TOP 3 RECOMMENDED INDICES")
    print(f"{'='*70}")

    for i, r in enumerate(rankings[:3], 1):
        print(f"\n  #{i} {r['symbol']}")
        print(f"     Score: {r['score']:.1f}")
        print(f"     Regime: {r['regime']} (Hurst={r['hurst']:.3f})")
        print(f"     Validated behaviors: {r['behaviors']}")
        print(f"     Best edge: {r['top_edge']*100:+.1f}% ({r['top_behavior']})")
        print(f"     Skewness: {r['skewness']:+.3f} | Vol clustering: {r['vol_cluster']:.3f}")

        # List behaviors for top 3
        if r['symbol'] in behavior_counts and behavior_counts[r['symbol']]['behaviors']:
            print(f"     Behaviors:")
            for b in behavior_counts[r['symbol']]['behaviors'][:5]:
                print(f"       [{b.edge*100:+.1f}%] {b.condition_desc} -> {b.outcome_desc} (N={b.occurrences})")

    print(f"\n{'='*70}")
    print(f"  RECOMMENDATION: Focus optimization on top 3 indices")
    print(f"  The system stays modular - same engine works on any index")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
