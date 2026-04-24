import pandas as pd, numpy as np

df = pd.read_parquet('data/mt5/Volatility_100_Index_H1_FULL.parquet')
d = df.copy()
d['ret'] = d['Close'].pct_change()
d['body'] = d['Close'] - d['Open']
d['body_pct'] = d['body'] / d['Open'] * 100
d['range'] = d['High'] - d['Low']
d['upper_wick'] = d['High'] - d[['Open','Close']].max(axis=1)
d['lower_wick'] = d[['Open','Close']].min(axis=1) - d['Low']
d['atr'] = d['range'].rolling(14).mean()

delta = d['Close'].diff()
gain = delta.where(delta>0,0).rolling(14).mean()
loss2 = (-delta.where(delta<0,0)).rolling(14).mean()
rs = gain/loss2.replace(0,np.nan)
d['rsi'] = 100-(100/(1+rs))
d['ema5'] = d['Close'].ewm(span=5).mean()
d['ema20'] = d['Close'].ewm(span=20).mean()
d['dist_ema20'] = (d['Close'] - d['ema20'])/d['ema20']*100
d['vol5'] = d['ret'].rolling(5).std()
d['vol20'] = d['ret'].rolling(20).std()
d['vol_ratio'] = d['vol5'] / d['vol20']

cu=0; cd=0; cup=[]; cdn=[]
for i in range(len(d)):
    if i>0 and d['ret'].iloc[i]>0: cu+=1; cd=0
    elif i>0 and d['ret'].iloc[i]<0: cd+=1; cu=0
    else: cu=0; cd=0
    cup.append(cu); cdn.append(cd)
d['consec_up']=cup; d['consec_down']=cdn

d['swing_high'] = False; d['swing_low'] = False
for i in range(3, len(d)-3):
    if (d['High'].iloc[i] >= d['High'].iloc[i-1] and d['High'].iloc[i] >= d['High'].iloc[i-2]
        and d['High'].iloc[i] >= d['High'].iloc[i+1] and d['High'].iloc[i] >= d['High'].iloc[i+2]):
        d.iloc[i, d.columns.get_loc('swing_high')] = True
    if (d['Low'].iloc[i] <= d['Low'].iloc[i-1] and d['Low'].iloc[i] <= d['Low'].iloc[i-2]
        and d['Low'].iloc[i] <= d['Low'].iloc[i+1] and d['Low'].iloc[i] <= d['Low'].iloc[i+2]):
        d.iloc[i, d.columns.get_loc('swing_low')] = True

d['sup_str']=0; d['res_str']=0
for i in range(200, len(d)):
    atr=d['atr'].iloc[i]
    if atr==0 or np.isnan(atr): continue
    price=d['Close'].iloc[i]
    rlows=d['Low'].iloc[max(0,i-300):i][d['swing_low'].iloc[max(0,i-300):i]].values
    rhighs=d['High'].iloc[max(0,i-300):i][d['swing_high'].iloc[max(0,i-300):i]].values
    d.iloc[i,d.columns.get_loc('sup_str')]=int(np.sum(np.abs(rlows-price)<atr))
    d.iloc[i,d.columns.get_loc('res_str')]=int(np.sum(np.abs(rhighs-price)<atr))

d['wick_ratio'] = d['upper_wick'] / d['atr']
d['bb_mid'] = d['Close'].rolling(20).mean()
d['bb_std'] = d['Close'].rolling(20).std()
d['bb_upper'] = d['bb_mid'] + 2*d['bb_std']
d['bb_lower'] = d['bb_mid'] - 2*d['bb_std']
d['bb_pct'] = (d['Close'] - d['bb_lower']) / (d['bb_upper'] - d['bb_lower'])
d['h4_bull'] = d['Close'].ewm(span=20).mean() > d['Close'].ewm(span=80).mean()
d['lower_wick_ratio'] = d['lower_wick'] / d['atr']

d2 = d.iloc[200:].dropna().copy()
bl_dn = (d2['Close'].shift(-5) < d2['Close']).mean()*100
bl_up = (d2['Close'].shift(-5) > d2['Close']).mean()*100

print("="*70)
print(f"  VOL 100 DEEP ANALYSIS | Baseline: UP={bl_up:.1f}% DN={bl_dn:.1f}%")
print("="*70)

# SELL
sell_conds = [
    ("Res3+ RSI>75", (d2['res_str']>=3) & (d2['rsi']>75)),
    ("Res3+ RSI>75 + bearH4", (d2['res_str']>=3) & (d2['rsi']>75) & (~d2['h4_bull'])),
    ("Res3+ RSI>75 + consec2+", (d2['res_str']>=3) & (d2['rsi']>75) & (d2['consec_up']>=2)),
    ("Res3+ RSI>75 + BB>0.9", (d2['res_str']>=3) & (d2['rsi']>75) & (d2['bb_pct']>0.9)),
    ("Res3+ RSI>75 + wick>0.3", (d2['res_str']>=3) & (d2['rsi']>75) & (d2['wick_ratio'].shift(1)>0.3)),
    ("Res3+ RSI>75 + vol_exp", (d2['res_str']>=3) & (d2['rsi']>75) & (d2['vol_ratio']>1.2)),
    ("Res3+ RSI>75 + red prev", (d2['res_str']>=3) & (d2['rsi']>75) & (d2['body_pct'].shift(1)<0)),
    ("Res3+ RSI>75 + dist>0.5%", (d2['res_str']>=3) & (d2['rsi']>75) & (d2['dist_ema20']>0.5)),
    ("Res2+ RSI>80", (d2['res_str']>=2) & (d2['rsi']>80)),
    ("Res2+ RSI>80 + bearH4", (d2['res_str']>=2) & (d2['rsi']>80) & (~d2['h4_bull'])),
    ("Res2+ RSI>80 + BB>0.95", (d2['res_str']>=2) & (d2['rsi']>80) & (d2['bb_pct']>0.95)),
    ("Res4+ RSI>70 + consec3+", (d2['res_str']>=4) & (d2['rsi']>70) & (d2['consec_up']>=3)),
    ("Res5+ RSI>65", (d2['res_str']>=5) & (d2['rsi']>65)),
    ("Res3+ RSI>70 + consec4+", (d2['res_str']>=3) & (d2['rsi']>70) & (d2['consec_up']>=4)),
    ("Res5+ RSI>70 + dist>0.3%", (d2['res_str']>=5) & (d2['rsi']>70) & (d2['dist_ema20']>0.3)),
    ("Res3+ vol_sq(vr<0.7) RSI>70", (d2['res_str']>=3) & (d2['vol_ratio']<0.7) & (d2['rsi']>70)),
    ("Res3+ EMA5 cross below EMA20", (d2['res_str']>=3) & (d2['ema5']<d2['ema20']) & (d2['ema5'].shift(1)>=d2['ema20'].shift(1))),
]

print(f"\n--- SELL CONDITIONS ---")
print(f"{'Condition':<45} {'5bar':>6} {'N':>5} {'Edge':>6}")
print("-"*65)

good_sell = []
for name, mask in sell_conds:
    n = mask.sum()
    if n < 15: continue
    d5 = (d2['Close'].shift(-5) < d2['Close'])[mask].mean()*100
    edge = d5 - bl_dn
    mk = " <<<" if edge > 5 else ""
    print(f"  {name:<43} {d5:>5.1f}% {n:>5} {edge:>+5.1f}%{mk}")
    if edge > 5: good_sell.append((name, d5, edge, n, mask))

# BUY
buy_conds = [
    ("Sup3+ RSI<30", (d2['sup_str']>=3) & (d2['rsi']<30)),
    ("Sup3+ RSI<30 + bullH4", (d2['sup_str']>=3) & (d2['rsi']<30) & (d2['h4_bull'])),
    ("Sup3+ RSI<30 + BB<0.1", (d2['sup_str']>=3) & (d2['rsi']<30) & (d2['bb_pct']<0.1)),
    ("Sup3+ RSI<35 + consec_dn3+", (d2['sup_str']>=3) & (d2['rsi']<35) & (d2['consec_down']>=3)),
    ("Sup4+ RSI<35", (d2['sup_str']>=4) & (d2['rsi']<35)),
    ("Sup4+ RSI<35 + bullH4", (d2['sup_str']>=4) & (d2['rsi']<35) & (d2['h4_bull'])),
    ("Sup5+ RSI<40", (d2['sup_str']>=5) & (d2['rsi']<40)),
    ("Sup3+ RSI<30 + lwick>0.3", (d2['sup_str']>=3) & (d2['rsi']<30) & (d2['lower_wick_ratio'].shift(1)>0.3)),
    ("Sup3+ RSI<25", (d2['sup_str']>=3) & (d2['rsi']<25)),
    ("Sup2+ RSI<25 + BB<0.05", (d2['sup_str']>=2) & (d2['rsi']<25) & (d2['bb_pct']<0.05)),
    ("Sup4+ RSI<30 + consec_dn2+", (d2['sup_str']>=4) & (d2['rsi']<30) & (d2['consec_down']>=2)),
    ("Sup3+ RSI<30 + green candle", (d2['sup_str']>=3) & (d2['rsi']<30) & (d2['body_pct']>0)),
]

print(f"\n--- BUY CONDITIONS ---")
print(f"{'Condition':<45} {'5bar':>6} {'N':>5} {'Edge':>6}")
print("-"*65)

good_buy = []
for name, mask in buy_conds:
    n = mask.sum()
    if n < 15: continue
    u5 = (d2['Close'].shift(-5) > d2['Close'])[mask].mean()*100
    edge = u5 - bl_up
    mk = " <<<" if edge > 3 else ""
    print(f"  {name:<43} {u5:>5.1f}% {n:>5} {edge:>+5.1f}%{mk}")
    if edge > 3: good_buy.append((name, u5, edge, n, mask))

# Year validation
print(f"\n{'='*70}")
print("  VALIDATION PAR ANNEE")
print(f"{'='*70}")

for name, rate, edge, n, mask in good_sell + good_buy:
    direction = "DN" if (name, rate, edge, n, mask) in good_sell else "UP"
    print(f"\n  {name} ({direction} {rate:.1f}%, edge={edge:.1f}%):")
    for year in sorted(d2.index.year.unique()):
        yd = d2[d2.index.year == year]
        ym = mask[d2.index.year == year]
        if ym.sum() < 3: continue
        if direction == "DN":
            yr = (yd['Close'].shift(-5) < yd['Close'])[ym].mean()*100
        else:
            yr = (yd['Close'].shift(-5) > yd['Close'])[ym].mean()*100
        print(f"    {year}: {yr:.1f}% (N={ym.sum()})")

# SL/TP simulation for best signals
print(f"\n{'='*70}")
print("  SIMULATION SL/TP")
print(f"{'='*70}")

atr_vals = d2['atr']
for name, rate, edge, n, mask in good_sell[:3]:
    idx_list = d2.index[mask]
    print(f"\n  {name}:")
    for sl in [1.5, 2.0, 2.5, 3.0]:
        for tp in [1.0, 1.5, 2.0, 2.5, 3.0]:
            w=0; l=0
            for idx in idx_list:
                pos = d2.index.get_loc(idx)
                if pos+20>=len(d2): continue
                entry=d2['Close'].iloc[pos]; atr=atr_vals.iloc[pos]
                if atr==0 or np.isnan(atr): continue
                sl_p=entry+sl*atr; tp_p=entry-tp*atr
                for bar in range(1,21):
                    if d2['High'].iloc[pos+bar]>=sl_p: l+=1; break
                    if d2['Low'].iloc[pos+bar]<=tp_p: w+=1; break
            tot=w+l
            if tot<10: continue
            pf=(w*tp)/(l*sl) if l>0 else 99
            wr=w/tot*100
            if pf>1.1:
                print(f"    SL={sl}x TP={tp}x | WR={wr:.0f}% PF={pf:.2f} Trades={tot}")

print("\nDone.")
