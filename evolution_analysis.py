#!/usr/bin/env python3
"""
ALGORITHM EVOLUTION ANALYSIS
==============================
Deriv's Crash 1000 algorithm evolves over time.
This script tracks WHAT changed, WHEN, and HOW to adapt.

Output:
  1. Year-by-year behavior comparison matrix
  2. Which behaviors appeared/disappeared each year
  3. How key metrics shift over time (spike frequency, volatility, etc.)
  4. Adaptive retraining strategy
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from scipy import stats
import warnings
warnings.filterwarnings('ignore')


def extract_or_load(symbol, tf_name, tf_mt5):
    """Load cached data or extract from MT5"""
    cache = Path(f'data/mt5/Crash_1000_{tf_name}_FULL.parquet')
    if cache.exists():
        df = pd.read_parquet(cache)
        print(f"  Loaded {tf_name}: {len(df)} candles from cache")
        return df

    if not mt5.initialize():
        print("  ERROR: MT5 not connected")
        return None

    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_range(symbol, tf_mt5, datetime(2019,1,1), datetime.now())
    mt5.shutdown()

    if rates is None or len(rates) == 0:
        return None

    df = pd.DataFrame(rates)
    df['datetime'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('datetime', inplace=True)
    df.rename(columns={'open':'Open','high':'High','low':'Low','close':'Close'}, inplace=True)
    df = df[['Open','High','Low','Close']]

    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache, compression='snappy')
    print(f"  Extracted {tf_name}: {len(df)} candles")
    return df


def compute_yearly_metrics(df, year_df, year):
    """Compute key algorithm metrics for a specific year"""
    d = year_df.copy()
    d['ret'] = d['Close'].pct_change()
    d = d.dropna()

    if len(d) < 100:
        return None

    ret = d['ret']

    # Basic stats
    metrics = {
        'year': year,
        'candles': len(d),
        'mean_ret': ret.mean(),
        'std_ret': ret.std(),
        'skewness': ret.skew(),
        'kurtosis': ret.kurt(),
        'pct_up': (ret > 0).mean(),
    }

    # Hurst exponent
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
    if len(vl) > 5:
        metrics['hurst'] = np.polyfit(np.log(vl), np.log(rs_vals), 1)[0]
    else:
        metrics['hurst'] = 0.5

    # Spike analysis
    ret_std = ret.rolling(100, min_periods=50).std()
    ret_mean = ret.rolling(100, min_periods=50).mean()
    crash_spikes = ret < (ret_mean - 3 * ret_std)
    crash_spikes = crash_spikes.dropna()

    metrics['spike_count'] = crash_spikes.sum()
    metrics['spike_rate_per_1000'] = crash_spikes.sum() / len(d) * 1000

    # Average spike amplitude
    spike_rets = ret[crash_spikes]
    metrics['avg_spike_amplitude'] = spike_rets.mean() if len(spike_rets) > 0 else 0

    # Time between spikes
    spike_indices = d.index[crash_spikes]
    if len(spike_indices) > 1:
        intervals = pd.Series(spike_indices).diff().dt.total_seconds() / 3600
        intervals = intervals.dropna()
        metrics['avg_spike_interval_hours'] = intervals.mean()
        metrics['std_spike_interval_hours'] = intervals.std()
    else:
        metrics['avg_spike_interval_hours'] = 0
        metrics['std_spike_interval_hours'] = 0

    # Volatility regime
    vol_20 = ret.rolling(20).std()
    metrics['avg_volatility'] = vol_20.mean()
    metrics['vol_of_vol'] = vol_20.std()  # volatility of volatility

    # Autocorrelation
    if len(ret) > 50:
        metrics['autocorr_1'] = ret.autocorr(1)
        metrics['autocorr_5'] = ret.autocorr(5)
        metrics['abs_autocorr_1'] = ret.abs().autocorr(1)
    else:
        metrics['autocorr_1'] = 0
        metrics['autocorr_5'] = 0
        metrics['abs_autocorr_1'] = 0

    # Post-crash recovery rate
    if len(spike_indices) > 5:
        recoveries = 0
        total_spikes = 0
        for idx in spike_indices:
            pos = d.index.get_loc(idx)
            if pos + 5 < len(d):
                total_spikes += 1
                future_ret = (d['Close'].iloc[pos+5] - d['Close'].iloc[pos]) / d['Close'].iloc[pos]
                if future_ret > 0:
                    recoveries += 1
        metrics['post_crash_recovery_rate'] = recoveries / max(1, total_spikes)
    else:
        metrics['post_crash_recovery_rate'] = 0

    # RSI oversold bounce rate
    delta = d['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    oversold_mask = (rsi >= 20) & (rsi < 35)
    if oversold_mask.sum() > 10:
        oversold_indices = d.index[oversold_mask]
        bounces = 0
        total = 0
        for idx in oversold_indices:
            pos = d.index.get_loc(idx)
            if pos + 5 < len(d):
                total += 1
                future = (d['Close'].iloc[pos+5] - d['Close'].iloc[pos]) / d['Close'].iloc[pos]
                if future > 0:
                    bounces += 1
        metrics['rsi_oversold_bounce_rate'] = bounces / max(1, total)
    else:
        metrics['rsi_oversold_bounce_rate'] = 0

    # EMA cross success rate
    ema5 = d['Close'].ewm(span=5).mean()
    ema20 = d['Close'].ewm(span=20).mean()
    bull_cross = (ema5 > ema20) & (ema5.shift(1) <= ema20.shift(1))

    if bull_cross.sum() > 5:
        cross_indices = d.index[bull_cross]
        successes = 0
        total = 0
        for idx in cross_indices:
            pos = d.index.get_loc(idx)
            if pos + 5 < len(d):
                total += 1
                future = (d['Close'].iloc[pos+5] - d['Close'].iloc[pos]) / d['Close'].iloc[pos]
                if future > 0:
                    successes += 1
        metrics['ema_cross_success_rate'] = successes / max(1, total)
    else:
        metrics['ema_cross_success_rate'] = 0

    return metrics


def detect_regime_changes(yearly_metrics):
    """Detect significant changes between consecutive years"""
    changes = []

    key_metrics = [
        ('spike_rate_per_1000', 'Crash frequency', 0.5),
        ('avg_spike_amplitude', 'Spike amplitude', 0.001),
        ('hurst', 'Hurst exponent', 0.03),
        ('std_ret', 'Volatility', 0.0003),
        ('skewness', 'Skewness', 0.15),
        ('post_crash_recovery_rate', 'Post-crash bounce rate', 0.08),
        ('rsi_oversold_bounce_rate', 'RSI oversold bounce rate', 0.05),
        ('ema_cross_success_rate', 'EMA cross success', 0.05),
        ('autocorr_1', 'Autocorrelation', 0.02),
    ]

    for i in range(1, len(yearly_metrics)):
        prev = yearly_metrics[i-1]
        curr = yearly_metrics[i]

        year_changes = []
        for metric, name, threshold in key_metrics:
            if metric in prev and metric in curr:
                diff = curr[metric] - prev[metric]
                pct_change = diff / abs(prev[metric]) * 100 if prev[metric] != 0 else 0

                if abs(diff) > threshold:
                    direction = "UP" if diff > 0 else "DOWN"
                    year_changes.append({
                        'metric': name,
                        'from': prev[metric],
                        'to': curr[metric],
                        'change': diff,
                        'pct': pct_change,
                        'direction': direction,
                    })

        if year_changes:
            changes.append({
                'from_year': prev['year'],
                'to_year': curr['year'],
                'changes': year_changes
            })

    return changes


def main():
    print("="*70)
    print("  CRASH 1000 - ALGORITHM EVOLUTION ANALYSIS")
    print("  Tracking how Deriv changes their algorithm over 7 years")
    print("="*70)

    # Load data
    h1 = extract_or_load('Crash 1000 Index', 'H1', mt5.TIMEFRAME_H1 if mt5.initialize() else None)
    if mt5.initialize(): mt5.shutdown()

    if h1 is None:
        print("No data available")
        return

    # Split by year
    years = {}
    for y in sorted(h1.index.year.unique()):
        ydf = h1[h1.index.year == y]
        if len(ydf) > 500:
            years[y] = ydf

    print(f"\n  Available years: {list(years.keys())}")
    print(f"  Total candles: {len(h1)}")

    # ============================================================
    # STEP 1: Year-by-year metrics
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  YEARLY ALGORITHM METRICS")
    print(f"{'#'*70}")

    yearly_metrics = []
    for year, ydf in sorted(years.items()):
        m = compute_yearly_metrics(h1, ydf, year)
        if m:
            yearly_metrics.append(m)

    # Print table
    print(f"\n  {'Year':>5} {'Candles':>8} {'Hurst':>6} {'Skew':>7} {'StdRet':>8} {'%UP':>5} {'Spikes':>7} {'SpkRate':>8} {'SpkAmp':>8} {'Recovery':>9} {'RSI_Bnc':>8} {'EMA_Suc':>8}")
    print(f"  {'-'*5} {'-'*8} {'-'*6} {'-'*7} {'-'*8} {'-'*5} {'-'*7} {'-'*8} {'-'*8} {'-'*9} {'-'*8} {'-'*8}")

    for m in yearly_metrics:
        print(f"  {m['year']:>5} {m['candles']:>8} {m['hurst']:>6.3f} {m['skewness']:>+7.3f} {m['std_ret']:>8.5f} {m['pct_up']*100:>4.1f}% {m['spike_count']:>7} {m['spike_rate_per_1000']:>7.1f}/k {m['avg_spike_amplitude']*100:>+7.3f}% {m['post_crash_recovery_rate']*100:>8.1f}% {m['rsi_oversold_bounce_rate']*100:>7.1f}% {m['ema_cross_success_rate']*100:>7.1f}%")

    # ============================================================
    # STEP 2: Trend detection in metrics
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  METRIC TRENDS OVER TIME")
    print(f"{'#'*70}")

    trend_metrics = [
        ('hurst', 'Hurst Exponent'),
        ('spike_rate_per_1000', 'Crash Spike Frequency'),
        ('avg_spike_amplitude', 'Spike Amplitude'),
        ('std_ret', 'Volatility'),
        ('post_crash_recovery_rate', 'Post-Crash Recovery Rate'),
        ('rsi_oversold_bounce_rate', 'RSI Oversold Bounce Rate'),
        ('ema_cross_success_rate', 'EMA Cross Success Rate'),
        ('skewness', 'Skewness'),
    ]

    print()
    for metric, name in trend_metrics:
        values = [m[metric] for m in yearly_metrics if metric in m]
        yrs = [m['year'] for m in yearly_metrics if metric in m]

        if len(values) < 3:
            continue

        # Linear trend
        slope, intercept, r, p, se = stats.linregress(range(len(values)), values)

        first = values[0]
        last = values[-1]
        change = last - first
        pct = change / abs(first) * 100 if first != 0 else 0

        trend = "INCREASING" if slope > 0 else "DECREASING"
        sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else ""

        print(f"  {name:<30} {first:>+10.4f} -> {last:>+10.4f} ({pct:>+6.1f}%) {trend:>12} p={p:.3f} {sig}")

    # ============================================================
    # STEP 3: Year-over-year changes
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  YEAR-OVER-YEAR CHANGES (what shifted)")
    print(f"{'#'*70}")

    changes = detect_regime_changes(yearly_metrics)

    for c in changes:
        significant = [ch for ch in c['changes'] if abs(ch['pct']) > 10]
        if significant:
            print(f"\n  {c['from_year']} -> {c['to_year']}:")
            for ch in sorted(significant, key=lambda x: -abs(x['pct'])):
                arrow = ">>>" if abs(ch['pct']) > 30 else ">>"  if abs(ch['pct']) > 20 else ">"
                print(f"    {arrow} {ch['metric']:<25} {ch['from']:.4f} -> {ch['to']:.4f} ({ch['pct']:>+.1f}%) {ch['direction']}")

    # ============================================================
    # STEP 4: Signal reliability over time
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  OUR EA SIGNALS - RELIABILITY BY YEAR")
    print(f"{'#'*70}")

    print(f"\n  {'Year':>5} {'Post-Crash':>11} {'RSI Bounce':>11} {'EMA Cross':>10} {'Verdict':>10}")
    print(f"  {'-'*5} {'-'*11} {'-'*11} {'-'*10} {'-'*10}")

    for m in yearly_metrics:
        pc = m['post_crash_recovery_rate'] * 100
        rb = m['rsi_oversold_bounce_rate'] * 100
        ec = m['ema_cross_success_rate'] * 100

        # Count how many signals are "good" (above 52%)
        good = sum(1 for x in [pc, rb, ec] if x > 52)
        verdict = "STRONG" if good >= 3 else "OK" if good >= 2 else "WEAK"

        print(f"  {m['year']:>5} {pc:>10.1f}% {rb:>10.1f}% {ec:>9.1f}% {verdict:>10}")

    # ============================================================
    # STEP 5: Adaptive strategy recommendation
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  ADAPTIVE STRATEGY - HOW TO STAY PROFITABLE")
    print(f"{'#'*70}")

    # Get most recent metrics
    recent = yearly_metrics[-1] if yearly_metrics else None
    prev = yearly_metrics[-2] if len(yearly_metrics) > 1 else None

    print(f"""
  FINDINGS:
  ---------
  1. Deriv's algorithm DOES evolve year over year
  2. Key changes observed:""")

    for metric, name in trend_metrics:
        values = [m[metric] for m in yearly_metrics if metric in m]
        if len(values) >= 3:
            slope, _, _, p, _ = stats.linregress(range(len(values)), values)
            if p < 0.1:
                direction = "increasing" if slope > 0 else "decreasing"
                print(f"     - {name} is {direction} over time (p={p:.3f})")

    print(f"""
  ADAPTATION STRATEGY:
  --------------------
  1. RETRAIN EVERY 3-6 MONTHS
     - Extract latest 6 months of H1 data from MT5
     - Re-run behavior_discovery.py
     - Compare with previous findings
     - Update EA if signal reliability changed

  2. MONITOR THESE KEY METRICS MONTHLY:
     - Post-crash recovery rate (currently: {recent['post_crash_recovery_rate']*100:.1f}%)
     - RSI oversold bounce rate (currently: {recent['rsi_oversold_bounce_rate']*100:.1f}%)
     - EMA cross success rate (currently: {recent['ema_cross_success_rate']*100:.1f}%)
     - Spike frequency (currently: {recent['spike_rate_per_1000']:.1f} per 1000 candles)

  3. ALERT THRESHOLDS (stop trading if):
     - Post-crash recovery drops below 45%
     - RSI bounce rate drops below 48%
     - Spike frequency changes by more than 30%
     - Hurst exponent drops below 0.55

  4. ROLLING WINDOW APPROACH:
     - Always train on the MOST RECENT 6-12 months
     - Don't use data older than 2 years
     - Recent patterns > old patterns
""")

    if recent and prev:
        print(f"  CURRENT STATUS ({recent['year']}):")
        print(f"  {'Metric':<25} {'Now':>8} {'vs Last Year':>12} {'Status':>8}")
        print(f"  {'-'*25} {'-'*8} {'-'*12} {'-'*8}")

        checks = [
            ('post_crash_recovery_rate', 'Post-crash recovery', 0.45),
            ('rsi_oversold_bounce_rate', 'RSI bounce rate', 0.48),
            ('ema_cross_success_rate', 'EMA cross success', 0.50),
            ('hurst', 'Hurst exponent', 0.55),
        ]

        all_ok = True
        for metric, name, threshold in checks:
            now = recent[metric]
            before = prev[metric]
            change = (now - before) / abs(before) * 100 if before != 0 else 0
            ok = now > threshold
            status = "OK" if ok else "WARNING"
            if not ok: all_ok = False
            print(f"  {name:<25} {now:>7.1%} {change:>+11.1f}% {status:>8}")

        print(f"\n  OVERALL: {'ALL SIGNALS HEALTHY - continue trading' if all_ok else 'WARNING - some signals degraded, review EA'}")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
