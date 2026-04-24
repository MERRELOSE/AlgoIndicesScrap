#!/usr/bin/env python3
"""
AUTO-RETRAIN PIPELINE
======================
Extracts latest data from MT5, re-runs behavior analysis,
compares with previous results, saves history for tracking.

Run manually or schedule with Task Scheduler / cron.
Recommended: every week or every 2 weeks.
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import json
import sys

sys.path.append(str(Path(__file__).parent.parent))

MONITORING_DIR = Path(__file__).parent.parent / 'data' / 'monitoring'
MONITORING_DIR.mkdir(parents=True, exist_ok=True)

INDICES = {
    'Crash 1000 Index': 'crash',
    'Crash 900 Index': 'crash',
    'Crash 500 Index': 'crash',
}

SIGNALS_TO_TRACK = [
    'post_crash_recovery',
    'rsi_oversold_bounce',
    'squeeze_uptrend',
    'ema_cross',
    'rsi_momentum',
    'consecutive_reversal',
]


def extract_latest(symbol, months=6):
    """Extract last N months of H1 data from MT5"""
    if not mt5.initialize():
        print(f"  MT5 not connected")
        return None

    mt5.symbol_select(symbol, True)
    start = datetime.now() - timedelta(days=months * 30)
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H1, start, datetime.now())
    mt5.shutdown()

    if rates is None or len(rates) == 0:
        return None

    df = pd.DataFrame(rates)
    df['datetime'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('datetime', inplace=True)
    df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close'}, inplace=True)
    return df[['Open', 'High', 'Low', 'Close']]


def compute_signal_health(df, window_months=3):
    """Compute reliability of each signal on recent data"""
    d = df.copy()
    d['ret'] = d['Close'].pct_change()

    # RSI
    delta = d['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    d['rsi'] = 100 - (100 / (1 + rs))

    # EMA
    d['ema5'] = d['Close'].ewm(span=5).mean()
    d['ema20'] = d['Close'].ewm(span=20).mean()

    # Vol
    d['vol5'] = d['ret'].rolling(5).std()
    d['vol20'] = d['ret'].rolling(20).std()
    d['vr'] = d['vol5'] / d['vol20']

    # Spikes
    rs2 = d['ret'].rolling(100, min_periods=50).std()
    rm2 = d['ret'].rolling(100, min_periods=50).mean()
    d['spike'] = (d['ret'] < rm2 - 3 * rs2).astype(int)

    d = d.dropna()

    # Use last N months only
    cutoff = d.index.max() - timedelta(days=window_months * 30)
    recent = d[d.index >= cutoff]

    if len(recent) < 200:
        return {}

    future5 = recent['Close'].shift(-5) / recent['Close'] - 1

    results = {}

    # Post-crash recovery
    spike_mask = recent['spike'].shift(1) == 1
    if spike_mask.sum() > 3:
        results['post_crash_recovery'] = {
            'rate': float((future5[spike_mask] > 0).mean() * 100),
            'n': int(spike_mask.sum()),
            'status': 'STRONG' if (future5[spike_mask] > 0).mean() > 0.55 else 'OK' if (future5[spike_mask] > 0).mean() > 0.50 else 'WEAK'
        }

    # RSI oversold bounce
    rsi_mask = (recent['rsi'] >= 20) & (recent['rsi'] < 35)
    if rsi_mask.sum() > 10:
        results['rsi_oversold_bounce'] = {
            'rate': float((future5[rsi_mask] > 0).mean() * 100),
            'n': int(rsi_mask.sum()),
            'status': 'STRONG' if (future5[rsi_mask] > 0).mean() > 0.55 else 'OK' if (future5[rsi_mask] > 0).mean() > 0.50 else 'WEAK'
        }

    # Squeeze + uptrend
    sq_mask = (recent['vr'] < 0.6) & (recent['ema5'] > recent['ema20'])
    if sq_mask.sum() > 10:
        results['squeeze_uptrend'] = {
            'rate': float((future5[sq_mask] > 0).mean() * 100),
            'n': int(sq_mask.sum()),
            'status': 'STRONG' if (future5[sq_mask] > 0).mean() > 0.55 else 'OK' if (future5[sq_mask] > 0).mean() > 0.50 else 'WEAK'
        }

    # EMA cross
    cross = (recent['ema5'] > recent['ema20']) & (recent['ema5'].shift(1) <= recent['ema20'].shift(1))
    if cross.sum() > 5:
        results['ema_cross'] = {
            'rate': float((future5[cross] > 0).mean() * 100),
            'n': int(cross.sum()),
            'status': 'STRONG' if (future5[cross] > 0).mean() > 0.55 else 'OK' if (future5[cross] > 0).mean() > 0.50 else 'WEAK'
        }

    # RSI momentum 70-80
    rm_mask = (recent['rsi'] >= 70) & (recent['rsi'] < 80)
    if rm_mask.sum() > 10:
        results['rsi_momentum'] = {
            'rate': float((future5[rm_mask] > 0).mean() * 100),
            'n': int(rm_mask.sum()),
            'status': 'STRONG' if (future5[rm_mask] > 0).mean() > 0.55 else 'OK' if (future5[rm_mask] > 0).mean() > 0.50 else 'WEAK'
        }

    # Hurst exponent
    ret = recent['ret']
    lags = range(2, min(30, len(ret) // 10))
    rs_vals = []
    for lag in lags:
        n_sub = min(len(ret) // lag, 30)
        rs_s = []
        for i in range(n_sub):
            sub = ret.values[i * lag:(i + 1) * lag]
            if len(sub) < 2: continue
            m = sub.mean()
            cum = np.cumsum(sub - m)
            R = cum.max() - cum.min()
            S = sub.std(ddof=1)
            if S > 0: rs_s.append(R / S)
        if rs_s: rs_vals.append(np.mean(rs_s))

    vl = list(lags)[:len(rs_vals)]
    hurst = np.polyfit(np.log(vl), np.log(rs_vals), 1)[0] if len(vl) > 5 else 0.5

    results['_meta'] = {
        'hurst': float(hurst),
        'volatility': float(ret.std()),
        'pct_up': float((ret > 0).mean() * 100),
        'candles': len(recent),
        'spike_count': int(recent['spike'].sum()),
        'spike_rate_per_1000': float(recent['spike'].sum() / len(recent) * 1000),
    }

    return results


def load_history(symbol):
    """Load previous monitoring history"""
    safe = symbol.replace(' ', '_')
    fpath = MONITORING_DIR / f'{safe}_history.json'
    if fpath.exists():
        with open(fpath) as f:
            return json.load(f)
    return []


def save_history(symbol, history):
    """Save monitoring history"""
    safe = symbol.replace(' ', '_')
    fpath = MONITORING_DIR / f'{safe}_history.json'
    with open(fpath, 'w') as f:
        json.dump(history, f, indent=2, default=str)


def detect_alerts(current, previous):
    """Compare current vs previous and detect degradations"""
    alerts = []

    if not previous:
        return alerts

    prev = previous[-1]  # most recent

    for signal in SIGNALS_TO_TRACK:
        if signal in current and signal in prev.get('signals', {}):
            curr_rate = current[signal]['rate']
            prev_rate = prev['signals'][signal]['rate']
            change = curr_rate - prev_rate

            if curr_rate < 45:
                alerts.append({
                    'level': 'CRITICAL',
                    'signal': signal,
                    'message': f'{signal} dropped to {curr_rate:.1f}% (below 45% threshold)',
                    'action': 'Consider disabling this signal in EA'
                })
            elif change < -5:
                alerts.append({
                    'level': 'WARNING',
                    'signal': signal,
                    'message': f'{signal} dropped by {abs(change):.1f}% ({prev_rate:.1f}% -> {curr_rate:.1f}%)',
                    'action': 'Monitor closely, may need adjustment'
                })

    # Check Hurst
    if '_meta' in current:
        hurst = current['_meta']['hurst']
        if hurst < 0.55:
            alerts.append({
                'level': 'WARNING',
                'signal': 'hurst',
                'message': f'Hurst dropped to {hurst:.3f} (trending behavior weakening)',
                'action': 'Market may be shifting to random walk'
            })

    return alerts


def run_retrain(verbose=True):
    """Main retraining pipeline"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')

    if verbose:
        print("=" * 60)
        print(f"  RETRAIN PIPELINE - {timestamp}")
        print("=" * 60)

    all_results = {}

    for symbol, idx_type in INDICES.items():
        if verbose:
            print(f"\n  --- {symbol} ---")

        # Extract latest 6 months
        df = extract_latest(symbol, months=6)
        if df is None:
            if verbose:
                print(f"  SKIP: No data from MT5")
            continue

        if verbose:
            print(f"  Data: {len(df)} candles | {df.index[0].date()} -> {df.index[-1].date()}")

        # Compute signal health on different windows
        health_3m = compute_signal_health(df, window_months=3)
        health_6m = compute_signal_health(df, window_months=6)

        # Load history
        history = load_history(symbol)

        # Detect alerts
        alerts = detect_alerts(health_3m, history)

        # Save new entry
        entry = {
            'timestamp': timestamp,
            'signals': health_3m,
            'signals_6m': health_6m,
            'alerts': alerts,
        }
        history.append(entry)

        # Keep last 50 entries max
        if len(history) > 50:
            history = history[-50:]

        save_history(symbol, history)

        all_results[symbol] = {
            'health_3m': health_3m,
            'health_6m': health_6m,
            'alerts': alerts,
        }

        if verbose:
            print(f"\n  Signal Health (last 3 months):")
            for sig in SIGNALS_TO_TRACK:
                if sig in health_3m:
                    h = health_3m[sig]
                    print(f"    {sig:<25} {h['rate']:>5.1f}% ({h['n']} samples) [{h['status']}]")

            if '_meta' in health_3m:
                m = health_3m['_meta']
                print(f"\n  Market State:")
                print(f"    Hurst: {m['hurst']:.3f} | Vol: {m['volatility']:.5f} | %UP: {m['pct_up']:.1f}%")
                print(f"    Spikes: {m['spike_count']} ({m['spike_rate_per_1000']:.1f}/1000 candles)")

            if alerts:
                print(f"\n  ALERTS:")
                for a in alerts:
                    print(f"    [{a['level']}] {a['message']}")
                    print(f"      Action: {a['action']}")
            else:
                print(f"\n  No alerts - all signals healthy")

    if verbose:
        print(f"\n{'=' * 60}")
        print(f"  Results saved to {MONITORING_DIR}")
        print(f"  Run 'streamlit run dashboard/app.py' to view dashboard")
        print(f"{'=' * 60}")

    return all_results


if __name__ == "__main__":
    run_retrain()
