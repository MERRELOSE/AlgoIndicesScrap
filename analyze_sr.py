import pandas as pd, numpy as np

df = pd.read_parquet('data/mt5/Crash_900_Index_H1_FULL.parquet')
d = df.copy()
d['ret'] = d['Close'].pct_change()
d['range'] = d['High'] - d['Low']
d['atr'] = d['range'].rolling(14).mean()

print("="*70)
print("  SUPPORTS/RESISTANCES & LIQUIDITE - Crash 900")
print("="*70)

# Swing highs/lows
d['swing_high'] = False
d['swing_low'] = False
for i in range(2, len(d)-2):
    if (d['High'].iloc[i] > d['High'].iloc[i-1] and d['High'].iloc[i] > d['High'].iloc[i-2] and
        d['High'].iloc[i] > d['High'].iloc[i+1] and d['High'].iloc[i] > d['High'].iloc[i+2]):
        d.iloc[i, d.columns.get_loc('swing_high')] = True
    if (d['Low'].iloc[i] < d['Low'].iloc[i-1] and d['Low'].iloc[i] < d['Low'].iloc[i-2] and
        d['Low'].iloc[i] < d['Low'].iloc[i+1] and d['Low'].iloc[i] < d['Low'].iloc[i+2]):
        d.iloc[i, d.columns.get_loc('swing_low')] = True

print(f"Swing Highs: {d['swing_high'].sum()}, Swing Lows: {d['swing_low'].sum()}")

# Support/resistance strength
d['sup_str'] = 0
d['res_str'] = 0
for i in range(200, len(d)):
    atr = d['atr'].iloc[i]
    if atr == 0 or np.isnan(atr): continue
    price = d['Close'].iloc[i]
    rlows = d['Low'].iloc[max(0,i-500):i][d['swing_low'].iloc[max(0,i-500):i]].values
    rhighs = d['High'].iloc[max(0,i-500):i][d['swing_high'].iloc[max(0,i-500):i]].values
    d.iloc[i, d.columns.get_loc('sup_str')] = int(np.sum(np.abs(rlows - price) < atr))
    d.iloc[i, d.columns.get_loc('res_str')] = int(np.sum(np.abs(rhighs - price) < atr))

d2 = d.iloc[200:].copy()
fut5 = d2['Close'].shift(-5) / d2['Close'] - 1
baseline_up = (fut5 > 0).mean() * 100
baseline_dn = (fut5 < 0).mean() * 100

print(f"\nBaseline UP 5bars: {baseline_up:.1f}%, DOWN: {baseline_dn:.1f}%")
print("\n--- SUPPORT (pres de swing lows) ---")
for s in [2,3,4,5]:
    m = d2['sup_str'] >= s
    n = m.sum()
    if n < 30: continue
    up = (fut5[m]>0).mean()*100
    print(f"  {s}+ swing lows: {up:.1f}% UP (N={n}) | edge={up-baseline_up:.1f}%")

print("\n--- RESISTANCE (pres de swing highs) ---")
for s in [2,3,4,5]:
    m = d2['res_str'] >= s
    n = m.sum()
    if n < 30: continue
    dn = (fut5[m]<0).mean()*100
    print(f"  {s}+ swing highs: {dn:.1f}% DN (N={n}) | edge={dn-baseline_dn:.1f}%")

# Liquidity sweeps
print("\n" + "="*70)
print("  LIQUIDITY SWEEPS")
print("="*70)

sweep_buy = 0; sweep_buy_win = 0
sweep_sell = 0; sweep_sell_win = 0

for i in range(100, len(d)-5):
    atr = d['atr'].iloc[i]
    if atr == 0 or np.isnan(atr): continue
    
    # BUY sweep: prix casse un swing low puis ferme au-dessus
    for j in range(max(0,i-50), i-2):
        if d['swing_low'].iloc[j]:
            sl = d['Low'].iloc[j]
            if d['Low'].iloc[i] < sl and d['Close'].iloc[i] > sl:
                sweep_buy += 1
                if d['Close'].iloc[i+5] > d['Close'].iloc[i]:
                    sweep_buy_win += 1
                break
    
    # SELL sweep: prix casse un swing high puis ferme en-dessous
    for j in range(max(0,i-50), i-2):
        if d['swing_high'].iloc[j]:
            sh = d['High'].iloc[j]
            if d['High'].iloc[i] > sh and d['Close'].iloc[i] < sh:
                sweep_sell += 1
                if d['Close'].iloc[i+5] < d['Close'].iloc[i]:
                    sweep_sell_win += 1
                break

print(f"\nBUY sweep (casse low + close above):")
print(f"  N={sweep_buy}, WinRate={sweep_buy_win/max(1,sweep_buy)*100:.1f}%, baseline={baseline_up:.1f}%, edge={sweep_buy_win/max(1,sweep_buy)*100-baseline_up:.1f}%")

print(f"\nSELL sweep (casse high + close below):")
print(f"  N={sweep_sell}, WinRate={sweep_sell_win/max(1,sweep_sell)*100:.1f}%, baseline={baseline_dn:.1f}%, edge={sweep_sell_win/max(1,sweep_sell)*100-baseline_dn:.1f}%")

# Combine avec RSI pour voir si ca ameliore
delta = d['Close'].diff()
gain = delta.where(delta>0,0).rolling(14).mean()
loss2 = (-delta.where(delta<0,0)).rolling(14).mean()
rs = gain/loss2.replace(0,np.nan)
d['rsi'] = 100-(100/(1+rs))

print("\n" + "="*70)
print("  COMBOS SUPPORT/RESISTANCE + INDICATEURS")
print("="*70)

d3 = d.iloc[200:].copy()
d3['fut5_up'] = d3['Close'].shift(-5) > d3['Close']
d3['fut5_dn'] = d3['Close'].shift(-5) < d3['Close']

combos_buy = [
    ("Support 3+ + RSI < 40", (d3['sup_str']>=3) & (d3['rsi']<40)),
    ("Support 3+ + RSI < 35", (d3['sup_str']>=3) & (d3['rsi']<35)),
    ("Support 4+ + RSI < 45", (d3['sup_str']>=4) & (d3['rsi']<45)),
    ("Support 2+ + RSI < 35", (d3['sup_str']>=2) & (d3['rsi']<35)),
    ("Support 3+ + RSI rebond (35-45)", (d3['sup_str']>=3) & (d3['rsi']>35) & (d3['rsi']<45)),
]

print("\n--- BUY combos (support + oversold) ---")
for name, mask in combos_buy:
    n = mask.sum()
    if n < 15: continue
    wr = d3['fut5_up'][mask].mean()*100
    print(f"  {name:<45} UP={wr:.1f}% (N={n}) edge={wr-baseline_up:.1f}%")

combos_sell = [
    ("Resistance 3+ + RSI > 70", (d3['res_str']>=3) & (d3['rsi']>70)),
    ("Resistance 3+ + RSI > 75", (d3['res_str']>=3) & (d3['rsi']>75)),
    ("Resistance 4+ + RSI > 65", (d3['res_str']>=4) & (d3['rsi']>65)),
    ("Resistance 2+ + RSI > 75", (d3['res_str']>=2) & (d3['rsi']>75)),
    ("Resistance 3+ + RSI 60-70", (d3['res_str']>=3) & (d3['rsi']>60) & (d3['rsi']<70)),
]

print("\n--- SELL combos (resistance + overbought) ---")
for name, mask in combos_sell:
    n = mask.sum()
    if n < 15: continue
    wr = d3['fut5_dn'][mask].mean()*100
    print(f"  {name:<45} DN={wr:.1f}% (N={n}) edge={wr-baseline_dn:.1f}%")

print("\nDone.")
