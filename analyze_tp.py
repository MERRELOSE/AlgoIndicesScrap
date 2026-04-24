#!/usr/bin/env python3
"""
TP CONTINUATION ANALYSIS - Crash 1000 Index
After TP is hit, does price continue? What's the optimal R:R?
"""
import pandas as pd, numpy as np
from pathlib import Path

df = pd.read_parquet('data/mt5/Crash_1000_H1_FULL.parquet')
df = df[df.index >= '2025-01-01'].copy()
print(f'Data: {len(df)} candles')

# Compute indicators vectorized
d = df.copy()
d['ret'] = d['Close'].pct_change()
d['ema5'] = d['Close'].ewm(span=5).mean()
d['ema20'] = d['Close'].ewm(span=20).mean()
d['atr'] = (d['High'] - d['Low']).rolling(14).mean()
d['vol5'] = d['ret'].rolling(5).std()
d['vol20'] = d['ret'].rolling(20).std()
d['vr'] = d['vol5'] / d['vol20']

delta = d['Close'].diff()
gain = delta.where(delta > 0, 0).rolling(14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
rs = gain / loss.replace(0, np.nan)
d['rsi'] = 100 - (100 / (1 + rs))

# Spike
rs2 = d['ret'].rolling(100, min_periods=50).std()
rm2 = d['ret'].rolling(100, min_periods=50).mean()
d['spike'] = (d['ret'] < rm2 - 3 * rs2).astype(int)

d = d.dropna().reset_index(drop=True)

# Find entries (simplified v5.1)
squeeze_up = (d['vr'] < 0.6) & (d['ema5'] > d['ema20'])
rsi_mom = (d['rsi'] >= 70) & (d['rsi'] < 80) & (d['ema5'] > d['ema20'])
rsi_os_consec = (d['rsi'] >= 25) & (d['rsi'] < 35)

# Spike in last 3 bars
spike_recent = d['spike'].rolling(3).max().fillna(0) > 0

signals = squeeze_up | rsi_mom | rsi_os_consec | spike_recent
entry_indices = d.index[signals].tolist()

# Sample if too many (speed)
if len(entry_indices) > 500:
    np.random.seed(42)
    entry_indices = sorted(np.random.choice(entry_indices, 500, replace=False))

print(f'Entry points: {len(entry_indices)}')

# For each entry, track MFE and TP hits
results = []
for idx in entry_indices:
    price = d.loc[idx, 'Close']
    atr = d.loc[idx, 'atr']
    if atr <= 0 or price <= 0:
        continue

    sl = price - 1.5 * atr
    max_price = price
    sl_hit = False
    tp_bars = {}

    # Look forward 50 bars
    end = min(idx + 51, len(d))
    for j in range(idx + 1, end):
        high = d.loc[j, 'High']
        low = d.loc[j, 'Low']

        if low <= sl:
            sl_hit = True
            break

        max_price = max(max_price, high)

        for mult in [1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]:
            k = mult
            if k not in tp_bars and high >= price + mult * atr:
                tp_bars[k] = j - idx

    mfe = (max_price - price) / atr

    results.append({
        'sl_hit': sl_hit,
        'mfe_atr': mfe,
        **{f'hit_{m}': m in tp_bars for m in [1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]},
        **{f'bars_{m}': tp_bars.get(m, 0) for m in [1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]},
    })

r = pd.DataFrame(results)
print(f'Analyzed: {len(r)} trades')
print(f'SL hit first: {r["sl_hit"].sum()} ({r["sl_hit"].mean()*100:.1f}%)')

print()
print('='*65)
print('  TP REACH ANALYSIS - Crash 1000 (SL fixed at 1.5x ATR)')
print('='*65)

print(f'\n  {"TP":>8} {"Reached":>10} {"Avg Bars":>10} {"EV (ATR)":>10} {"Worth?":>8}')
print(f'  {"-"*8} {"-"*10} {"-"*10} {"-"*10} {"-"*8}')

best_ev = -99
best_tp = 3.0
for mult in [1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]:
    col = f'hit_{mult}'
    pct = r[col].mean() * 100
    bars_col = f'bars_{mult}'
    avg_b = r.loc[r[col], bars_col].mean() if r[col].sum() > 0 else 0

    # EV = P(win)*TP - P(loss)*SL
    ev = (pct / 100 * mult) - ((100 - pct) / 100 * 1.5)
    worth = 'YES' if ev > 0 else 'no'
    marker = ''

    if ev > best_ev:
        best_ev = ev
        best_tp = mult

    print(f'  {mult:>6.1f}x  {pct:>8.1f}%  {avg_b:>8.1f}b  {ev:>+8.3f}    {worth:>6}{marker}')

print()
print('='*65)
print('  MAX FAVORABLE EXCURSION (how far price actually goes)')
print('='*65)
mfe = r['mfe_atr']
print(f'\n  25th percentile: {mfe.quantile(0.25):.2f}x ATR')
print(f'  50th percentile: {mfe.quantile(0.50):.2f}x ATR (median)')
print(f'  75th percentile: {mfe.quantile(0.75):.2f}x ATR')
print(f'  90th percentile: {mfe.quantile(0.90):.2f}x ATR')
print(f'  95th percentile: {mfe.quantile(0.95):.2f}x ATR')
print(f'  Mean:            {mfe.mean():.2f}x ATR')
print(f'  Max:             {mfe.max():.2f}x ATR')

print()
print('='*65)
print('  AFTER 3.0x ATR TP - Does price continue?')
print('='*65)
tp3 = r[r['hit_3.0'] == True]
print(f'\n  Trades that reached 3.0x ATR: {len(tp3)} / {len(r)} ({len(tp3)/len(r)*100:.1f}%)')
if len(tp3) > 0:
    for m in [4.0, 5.0, 6.0, 8.0, 10.0]:
        col = f'hit_{m}'
        cnt = tp3[col].sum()
        print(f'  ... then continued to {m:.0f}x ATR: {cnt} ({cnt/len(tp3)*100:.1f}%)')
    print(f'  Avg MFE of TP winners: {tp3["mfe_atr"].mean():.2f}x ATR')
    print(f'  Median MFE:            {tp3["mfe_atr"].median():.2f}x ATR')

print()
print('='*65)
print(f'  RECOMMENDATION: Optimal TP = {best_tp:.1f}x ATR (EV={best_ev:+.3f})')
print(f'  Current TP: 3.0x ATR')
if best_tp != 3.0:
    curr_ev = r['hit_3.0'].mean() * 3.0 - (1 - r['hit_3.0'].mean()) * 1.5
    print(f'  Current EV: {curr_ev:+.3f} ATR')
    print(f'  Optimal EV: {best_ev:+.3f} ATR ({(best_ev/curr_ev-1)*100:+.1f}% better)')
print('='*65)
