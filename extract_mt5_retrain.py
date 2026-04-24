#!/usr/bin/env python3
"""
EXTRACT MASSIVE HISTORY FROM MT5 + RETRAIN BEHAVIOR MODEL
==========================================================
MT5 has data from April 2019 = ~7 years!
vs our previous 12 months from Deriv API.

This script:
1. Extracts ALL available H1 + H4 data from MT5
2. Re-runs behavior discovery on the full dataset
3. Compares with our 12-month findings
4. Identifies which behaviors are TRULY robust across years
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# Import our behavior discovery engine
import sys
sys.path.append(str(Path.cwd()))
from behavior_discovery import prepare_data, Behavior, run_discovery


def extract_mt5_data(symbol, timeframe_mt5, timeframe_name, start_year=2019):
    """Extract all available data from MT5"""

    start_date = datetime(start_year, 1, 1)

    # MT5 timeframe mapping
    tf_map = {
        'M15': mt5.TIMEFRAME_M15,
        'H1': mt5.TIMEFRAME_H1,
        'H4': mt5.TIMEFRAME_H4,
        'D1': mt5.TIMEFRAME_D1,
    }

    tf = tf_map.get(timeframe_name, mt5.TIMEFRAME_H1)

    print(f"\n  Extracting {symbol} {timeframe_name} from {start_year}...")

    # Activate symbol first
    mt5.symbol_select(symbol, True)

    # Use copy_rates_range (copy_rates_from has issues with large requests)
    end_date = datetime.now()
    rates = mt5.copy_rates_range(symbol, tf, start_date, end_date)

    if rates is None or len(rates) == 0:
        print(f"  ERROR: No data returned")
        return None

    df = pd.DataFrame(rates)
    df['datetime'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('datetime', inplace=True)

    # Rename columns to match our format
    df.rename(columns={
        'open': 'Open',
        'high': 'High',
        'low': 'Low',
        'close': 'Close',
        'tick_volume': 'Volume'
    }, inplace=True)

    # Keep only OHLCV
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']]

    days = (df.index[-1] - df.index[0]).days
    years = days / 365.25

    print(f"  OK: {len(df)} candles | {days} days ({years:.1f} years)")
    print(f"  Range: {df.index[0].date()} -> {df.index[-1].date()}")

    return df


def split_by_year(df):
    """Split dataframe into yearly chunks for consistency testing"""
    years = {}
    for year in df.index.year.unique():
        year_df = df[df.index.year == year]
        if len(year_df) > 100:
            years[year] = year_df
    return years


def run_full_analysis():
    """Main analysis pipeline"""

    print("="*70)
    print("  MT5 MASSIVE DATA EXTRACTION + BEHAVIOR RETRAINING")
    print("="*70)

    # Initialize MT5
    if not mt5.initialize():
        print("ERROR: Cannot connect to MT5. Make sure it's running.")
        return

    info = mt5.account_info()
    print(f"\n  MT5 Connected: {info.login} @ {info.server}")
    print(f"  Balance: ${info.balance:.2f}")

    symbol = 'Crash 1000 Index'
    output_dir = Path('data/mt5')
    output_dir.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # STEP 1: Extract all data
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  STEP 1: EXTRACTION FROM MT5")
    print(f"{'#'*70}")

    datasets = {}

    for tf in ['H1', 'H4']:
        df = extract_mt5_data(symbol, None, tf, start_year=2019)
        if df is not None:
            # Save
            fpath = output_dir / f"Crash_1000_{tf}_FULL.parquet"
            df.to_parquet(fpath, compression='snappy')
            datasets[tf] = df
            print(f"  Saved: {fpath}")

    mt5.shutdown()
    print("\n  MT5 disconnected")

    if 'H1' not in datasets:
        print("ERROR: No H1 data extracted")
        return

    h1_full = datasets['H1']

    # ============================================================
    # STEP 2: Compare data volumes
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  STEP 2: DATA COMPARISON")
    print(f"{'#'*70}")

    # Load old API data
    old_path = Path('data/raw/Crash_1000_Index_H1.parquet')
    if old_path.exists():
        old_df = pd.read_parquet(old_path)
        print(f"\n  Old (Deriv API):  {len(old_df):>7} candles | {(old_df.index[-1]-old_df.index[0]).days:>4} days")
    else:
        print(f"\n  Old data not found")

    print(f"  New (MT5 full):   {len(h1_full):>7} candles | {(h1_full.index[-1]-h1_full.index[0]).days:>4} days")
    print(f"  Ratio:            {len(h1_full)/len(old_df) if old_path.exists() else '?'}x more data")

    # ============================================================
    # STEP 3: Run behavior discovery on FULL data
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  STEP 3: BEHAVIOR DISCOVERY ON {len(h1_full)} CANDLES ({(h1_full.index[-1]-h1_full.index[0]).days/365:.1f} YEARS)")
    print(f"{'#'*70}")

    valid_full, invalid_full = run_discovery(h1_full, symbol, 'H1_FULL')

    # ============================================================
    # STEP 4: Year-by-year consistency check
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  STEP 4: YEAR-BY-YEAR CONSISTENCY")
    print(f"{'#'*70}")

    yearly = split_by_year(h1_full)
    print(f"\n  Available years: {sorted(yearly.keys())}")

    # Track which behaviors appear each year
    behavior_yearly = {}

    for year, year_df in sorted(yearly.items()):
        print(f"\n  --- {year} ({len(year_df)} candles) ---")
        try:
            valid_year, _ = run_discovery(year_df, symbol, f'H1_{year}')
            for b in valid_year:
                base = b.name.split('_next_')[0] if '_next_' in b.name else b.name
                if base not in behavior_yearly:
                    behavior_yearly[base] = {}
                behavior_yearly[base][year] = {
                    'edge': b.edge,
                    'occurrences': b.occurrences,
                    'rate': b.outcome_rate,
                    'pvalue': b.p_value
                }
        except Exception as e:
            print(f"    Error: {e}")

    # ============================================================
    # STEP 5: Find TRULY ROBUST behaviors (appear in 3+ years)
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  STEP 5: TRULY ROBUST BEHAVIORS (validated across years)")
    print(f"{'#'*70}")

    print(f"\n  {'Behavior':<40} {'Years':>6} {'Avg Edge':>9} {'Direction':>10}")
    print(f"  {'-'*40} {'-'*6} {'-'*9} {'-'*10}")

    robust = []
    for bname, years_data in sorted(behavior_yearly.items(), key=lambda x: -len(x[1])):
        n_years = len(years_data)
        avg_edge = np.mean([d['edge'] for d in years_data.values()])
        edges = [d['edge'] for d in years_data.values()]

        # Check if direction is consistent (all positive or all negative)
        all_positive = all(e > 0 for e in edges)
        all_negative = all(e < 0 for e in edges)
        consistent = all_positive or all_negative

        direction = "CONSISTENT" if consistent else "MIXED"

        if n_years >= 3:
            marker = " <<<" if consistent else ""
            print(f"  {bname:<40} {n_years:>6} {avg_edge*100:>+8.1f}% {direction:>10}{marker}")

            if consistent:
                robust.append({
                    'name': bname,
                    'years': n_years,
                    'avg_edge': avg_edge,
                    'direction': 'positive' if all_positive else 'negative',
                    'details': years_data
                })

        # Print year details for behaviors in 4+ years
        if n_years >= 4:
            for y, d in sorted(years_data.items()):
                print(f"    {y}: edge={d['edge']*100:+.1f}% N={d['occurrences']} p={d['pvalue']:.4f}")

    # ============================================================
    # STEP 6: Compare with our EA signals
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  STEP 6: EA SIGNAL VALIDATION")
    print(f"{'#'*70}")

    ea_signals = [
        'crash_recovery',
        'rsi_oversold',
        'rsi_overbought',
        'vol_squeeze',
        'doji_candle',
        'bullish_ema_cross',
        'high_vol_overbought',
    ]

    print(f"\n  Our EA signals vs full {len(h1_full)} candle dataset:")
    print()

    for b in valid_full:
        # Check if this behavior relates to any EA signal
        for ea_sig in ea_signals:
            if ea_sig in b.name:
                status = "CONFIRMED" if abs(b.edge) > 0.02 else "WEAK"
                print(f"  {b.name}")
                print(f"    Edge: {b.edge*100:+.1f}% | N={b.occurrences} | p={b.p_value:.4f}")
                print(f"    1st half: {b.first_half_rate*100:.1f}% | 2nd half: {b.second_half_rate*100:.1f}%")
                print(f"    Status: [{status}]")
                print()
                break

    # ============================================================
    # SUMMARY
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"#  FINAL SUMMARY")
    print(f"{'#'*70}")

    print(f"\n  Data: {len(h1_full)} candles over {(h1_full.index[-1]-h1_full.index[0]).days/365:.1f} years")
    print(f"  Behaviors found (full data): {len(valid_full)}")
    print(f"  Behaviors consistent across 3+ years: {len(robust)}")

    if robust:
        print(f"\n  TOP ROBUST BEHAVIORS (use these with confidence):")
        for r in sorted(robust, key=lambda x: abs(x['avg_edge']), reverse=True)[:10]:
            print(f"    {r['name']}: {r['avg_edge']*100:+.1f}% edge | found in {r['years']} years | {r['direction']}")

    print(f"\n  RECOMMENDATION:")
    if len(robust) >= 3:
        print(f"  {len(robust)} behaviors validated across years. System is ROBUST.")
        print(f"  Safe to continue with demo live trading.")
    else:
        print(f"  Only {len(robust)} robust behaviors. Consider adjusting EA signals.")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    run_full_analysis()
