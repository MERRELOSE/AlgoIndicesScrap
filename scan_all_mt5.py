#!/usr/bin/env python3
"""
FULL 7-YEAR SCAN OF ALL DERIV INDICES VIA MT5
===============================================
Extract maximum history for every index, run behavior discovery,
year-by-year consistency check, and rank by exploitability.
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from scipy import stats
import sys
import warnings
warnings.filterwarnings('ignore')

sys.path.append(str(Path.cwd()))
from behavior_discovery import prepare_data, Behavior, run_discovery

ALL_INDICES = [
    'Crash 500 Index',
    'Crash 1000 Index',
    'Boom 500 Index',
    'Boom 1000 Index',
    'Volatility 10 Index',
    'Volatility 25 Index',
    'Volatility 50 Index',
    'Volatility 75 Index',
    'Volatility 100 Index',
    'Step Index',
]


def extract_from_mt5(symbol, tf_name):
    """Extract all available H1 data from MT5"""
    tf_map = {'H1': mt5.TIMEFRAME_H1, 'H4': mt5.TIMEFRAME_H4}
    tf = tf_map.get(tf_name, mt5.TIMEFRAME_H1)

    cache = Path(f'data/mt5/{symbol.replace(" ", "_")}_{tf_name}_FULL.parquet')
    if cache.exists():
        df = pd.read_parquet(cache)
        if len(df) > 5000:
            return df

    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_range(symbol, tf, datetime(2018, 1, 1), datetime.now())

    if rates is None or len(rates) == 0:
        return None

    df = pd.DataFrame(rates)
    df['datetime'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('datetime', inplace=True)
    df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close'}, inplace=True)
    df = df[['Open', 'High', 'Low', 'Close']]

    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache, compression='snappy')
    return df


def quick_stats(df):
    """Quick statistical profile"""
    d = df.copy()
    d['ret'] = d['Close'].pct_change()
    d = d.dropna()
    ret = d['ret']

    # Hurst
    lags = range(2, min(50, len(ret)//10))
    rs_vals = []
    for lag in lags:
        n_sub = min(len(ret)//lag, 50)
        rs_s = []
        for i in range(n_sub):
            sub = ret.values[i*lag:(i+1)*lag]
            if len(sub) < 2: continue
            m = sub.mean()
            cum = np.cumsum(sub - m)
            R = cum.max() - cum.min()
            S = sub.std(ddof=1)
            if S > 0: rs_s.append(R/S)
        if rs_s: rs_vals.append(np.mean(rs_s))
    vl = list(lags)[:len(rs_vals)]
    hurst = np.polyfit(np.log(vl), np.log(rs_vals), 1)[0] if len(vl) > 5 else 0.5

    # Spikes
    ret_std = ret.rolling(100, min_periods=50).std()
    ret_mean = ret.rolling(100, min_periods=50).mean()
    crash_spikes = (ret < (ret_mean - 3 * ret_std)).dropna().sum()
    boom_spikes = (ret > (ret_mean + 3 * ret_std)).dropna().sum()

    return {
        'candles': len(d),
        'days': (d.index[-1] - d.index[0]).days,
        'years': (d.index[-1] - d.index[0]).days / 365.25,
        'hurst': hurst,
        'skewness': ret.skew(),
        'kurtosis': ret.kurt(),
        'std': ret.std(),
        'pct_up': (ret > 0).mean(),
        'crash_spikes': crash_spikes,
        'boom_spikes': boom_spikes,
        'mean_ret': ret.mean(),
    }


def yearly_consistency(df, symbol):
    """Run behavior discovery per year, track which survive across years"""
    yearly_behaviors = {}
    years_data = {}

    for year in sorted(df.index.year.unique()):
        ydf = df[df.index.year == year]
        if len(ydf) < 1000:
            continue

        years_data[year] = len(ydf)

        try:
            valid, _ = run_discovery(ydf, symbol, f'H1_{year}')
            for b in valid:
                name = b.name
                if name not in yearly_behaviors:
                    yearly_behaviors[name] = {}
                yearly_behaviors[name][year] = {
                    'edge': b.edge,
                    'n': b.occurrences,
                    'rate': b.outcome_rate,
                    'p': b.p_value,
                }
        except:
            pass

    return yearly_behaviors, years_data


def score_index_v2(stats, full_behaviors, yearly_behaviors, n_years):
    """Score index exploitability based on 7-year data"""
    score = 0

    # 1. Behaviors found on full data
    score += len(full_behaviors) * 3

    # 2. Behaviors consistent across 3+ years (most important)
    robust_count = 0
    for bname, years in yearly_behaviors.items():
        if len(years) >= 3:
            edges = [d['edge'] for d in years.values()]
            all_same_sign = all(e > 0 for e in edges) or all(e < 0 for e in edges)
            if all_same_sign:
                robust_count += 1
                avg_edge = abs(np.mean(edges))
                score += avg_edge * 100 + len(years) * 2

    # 3. Hurst away from 0.5
    score += abs(stats['hurst'] - 0.5) * 80

    # 4. Skewness (directional bias)
    score += abs(stats['skewness']) * 8

    # 5. Enough data
    if stats['years'] < 3:
        score *= 0.5

    return round(score, 1), robust_count


def main():
    print("="*70)
    print("  7-YEAR FULL SCAN - ALL DERIV INDICES")
    print("  Finding the most exploitable indices with proven behaviors")
    print("="*70)

    # Connect MT5
    if not mt5.initialize():
        print("ERROR: MT5 not connected")
        return

    info = mt5.account_info()
    print(f"\n  MT5: {info.login} @ {info.server}")

    Path('data/mt5').mkdir(parents=True, exist_ok=True)

    # ============================================================
    # STEP 1: Extract all data
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  STEP 1: EXTRACTION")
    print(f"{'#'*70}")

    datasets = {}
    for symbol in ALL_INDICES:
        print(f"\n  {symbol}...", end=' ')
        df = extract_from_mt5(symbol, 'H1')
        if df is not None and len(df) > 1000:
            days = (df.index[-1] - df.index[0]).days
            print(f"{len(df)} candles | {days/365.25:.1f} years | {df.index[0].date()} -> {df.index[-1].date()}")
            datasets[symbol] = df
        else:
            print("FAILED or not enough data")

    mt5.shutdown()
    print(f"\n  Extracted: {len(datasets)}/{len(ALL_INDICES)} indices")

    # ============================================================
    # STEP 2: Quick stats
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  STEP 2: STATISTICAL PROFILES (7 YEARS)")
    print(f"{'#'*70}")

    all_stats = {}
    for symbol, df in datasets.items():
        all_stats[symbol] = quick_stats(df)

    print(f"\n  {'Symbol':<25} {'Years':>5} {'Candles':>8} {'Hurst':>6} {'Skew':>7} {'%UP':>5} {'CrashSpk':>9} {'BoomSpk':>8}")
    print(f"  {'-'*25} {'-'*5} {'-'*8} {'-'*6} {'-'*7} {'-'*5} {'-'*9} {'-'*8}")

    for sym in ALL_INDICES:
        if sym in all_stats:
            s = all_stats[sym]
            print(f"  {sym:<25} {s['years']:>5.1f} {s['candles']:>8} {s['hurst']:>6.3f} {s['skewness']:>+7.3f} {s['pct_up']*100:>4.1f}% {s['crash_spikes']:>9} {s['boom_spikes']:>8}")

    # ============================================================
    # STEP 3: Behavior discovery on full data
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  STEP 3: BEHAVIOR DISCOVERY (FULL HISTORY)")
    print(f"{'#'*70}")

    all_full_behaviors = {}
    for symbol, df in datasets.items():
        print(f"\n  Scanning {symbol}...")
        try:
            valid, _ = run_discovery(df, symbol, 'H1_FULL')
            all_full_behaviors[symbol] = valid
            print(f"  -> {len(valid)} validated behaviors")
        except Exception as e:
            print(f"  -> ERROR: {e}")
            all_full_behaviors[symbol] = []

    # ============================================================
    # STEP 4: Year-by-year consistency
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  STEP 4: YEAR-BY-YEAR CONSISTENCY")
    print(f"{'#'*70}")

    all_yearly = {}
    for symbol, df in datasets.items():
        print(f"\n  {symbol}...")
        yearly_b, years_data = yearly_consistency(df, symbol)
        all_yearly[symbol] = yearly_b

        # Count robust behaviors
        robust = 0
        for bname, years in yearly_b.items():
            if len(years) >= 3:
                edges = [d['edge'] for d in years.values()]
                if all(e > 0 for e in edges) or all(e < 0 for e in edges):
                    robust += 1

        n_years = len(years_data)
        print(f"    {n_years} years analyzed | {len(yearly_b)} behaviors found | {robust} robust (3+ years consistent)")

    # ============================================================
    # STEP 5: Final ranking
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  STEP 5: FINAL RANKING")
    print(f"{'#'*70}")

    rankings = []
    for symbol in ALL_INDICES:
        if symbol not in all_stats:
            continue

        s = all_stats[symbol]
        full_b = all_full_behaviors.get(symbol, [])
        yearly_b = all_yearly.get(symbol, {})
        n_years = len(set(y for bdata in yearly_b.values() for y in bdata.keys()))

        score, robust_count = score_index_v2(s, full_b, yearly_b, n_years)

        rankings.append({
            'symbol': symbol,
            'score': score,
            'hurst': s['hurst'],
            'skew': s['skewness'],
            'years': s['years'],
            'full_behaviors': len(full_b),
            'robust_behaviors': robust_count,
            'pct_up': s['pct_up'],
        })

    rankings.sort(key=lambda x: x['score'], reverse=True)

    print(f"\n  {'Rank':>4} {'Symbol':<25} {'Score':>6} {'Hurst':>6} {'Skew':>7} {'Years':>5} {'Behaviors':>10} {'Robust':>7}")
    print(f"  {'-'*4} {'-'*25} {'-'*6} {'-'*6} {'-'*7} {'-'*5} {'-'*10} {'-'*7}")

    for i, r in enumerate(rankings, 1):
        marker = " <<<" if i <= 4 else ""
        print(f"  {i:>4} {r['symbol']:<25} {r['score']:>6.1f} {r['hurst']:>6.3f} {r['skew']:>+7.3f} {r['years']:>5.1f} {r['full_behaviors']:>10} {r['robust_behaviors']:>7}{marker}")

    # ============================================================
    # STEP 6: Top 4 details
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  TOP 4 - DETAILED ANALYSIS")
    print(f"{'#'*70}")

    for i, r in enumerate(rankings[:4], 1):
        symbol = r['symbol']
        print(f"\n  {'='*60}")
        print(f"  #{i} {symbol}")
        print(f"  Score: {r['score']} | Hurst: {r['hurst']:.3f} | Skew: {r['skew']:+.3f}")
        print(f"  {r['full_behaviors']} behaviors on full data | {r['robust_behaviors']} robust across years")
        print(f"  {'='*60}")

        # Top behaviors on full data
        full_b = all_full_behaviors.get(symbol, [])
        if full_b:
            print(f"\n  Top behaviors (full {r['years']:.1f} years):")
            for b in full_b[:8]:
                print(f"    [{b.edge*100:+.1f}%] {b.condition_desc}")
                print(f"      -> {b.outcome_desc} | N={b.occurrences} | p={b.p_value:.4f}")

        # Robust behaviors (3+ years)
        yearly_b = all_yearly.get(symbol, {})
        robust_list = []
        for bname, years in yearly_b.items():
            if len(years) >= 3:
                edges = [d['edge'] for d in years.values()]
                all_pos = all(e > 0 for e in edges)
                all_neg = all(e < 0 for e in edges)
                if all_pos or all_neg:
                    robust_list.append({
                        'name': bname,
                        'years': len(years),
                        'avg_edge': np.mean(edges),
                        'direction': 'positive' if all_pos else 'negative',
                    })

        if robust_list:
            robust_list.sort(key=lambda x: -abs(x['avg_edge']))
            print(f"\n  Robust behaviors (consistent 3+ years):")
            for rb in robust_list[:8]:
                print(f"    {rb['name']:<40} {rb['avg_edge']*100:+.1f}% edge | {rb['years']} years | {rb['direction']}")

        # Signal reliability on most recent year
        df = datasets[symbol]
        recent_year = df.index.year.max()
        recent_df = df[df.index.year == recent_year]
        if len(recent_df) > 500:
            recent_d = recent_df.copy()
            recent_d['ret'] = recent_d['Close'].pct_change()
            recent_d = recent_d.dropna()

            # RSI
            delta = recent_d['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss.replace(0, np.nan)
            recent_d['rsi'] = 100 - (100 / (1 + rs))

            # EMA
            recent_d['ema5'] = recent_d['Close'].ewm(span=5).mean()
            recent_d['ema20'] = recent_d['Close'].ewm(span=20).mean()

            # Vol
            recent_d['vol5'] = recent_d['ret'].rolling(5).std()
            recent_d['vol20'] = recent_d['ret'].rolling(20).std()
            recent_d['vol_ratio'] = recent_d['vol5'] / recent_d['vol20']

            recent_d = recent_d.dropna()
            future = recent_d['Close'].shift(-5) / recent_d['Close'] - 1

            print(f"\n  Signal reliability ({recent_year} - most recent):")

            tests = [
                ('RSI 20-35 bounce', (recent_d['rsi'] >= 20) & (recent_d['rsi'] < 35)),
                ('RSI 70-80 momentum', (recent_d['rsi'] >= 70) & (recent_d['rsi'] < 80)),
                ('Squeeze+uptrend', (recent_d['vol_ratio'] < 0.6) & (recent_d['ema5'] > recent_d['ema20'])),
                ('EMA bullish cross', (recent_d['ema5'] > recent_d['ema20']) & (recent_d['ema5'].shift(1) <= recent_d['ema20'].shift(1))),
            ]

            for name, mask in tests:
                if mask.sum() > 10:
                    rate = (future[mask] > 0).mean() * 100
                    status = 'STRONG' if rate > 55 else 'OK' if rate > 50 else 'WEAK'
                    print(f"    {name:<25} {rate:.1f}% up rate | N={mask.sum()} [{status}]")

    # ============================================================
    # SUMMARY
    # ============================================================
    print(f"\n\n{'#'*70}")
    print(f"#  RECOMMENDATION")
    print(f"{'#'*70}")

    print(f"\n  Top 4 indices to build trading systems for:")
    for i, r in enumerate(rankings[:4], 1):
        print(f"    {i}. {r['symbol']} (score={r['score']}, {r['robust_behaviors']} robust signals)")

    print(f"\n  Already done: Crash 1000 Index (v5.1 EA running on demo)")
    print(f"  Next: Build EAs for the other top indices")
    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
