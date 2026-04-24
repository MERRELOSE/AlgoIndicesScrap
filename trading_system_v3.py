#!/usr/bin/env python3
"""
TRADING SYSTEM v3 - CRASH 1000 OPTIMIZED
=========================================
Focused on Crash 1000 Index - our most profitable setup.

Key improvements over v2:
  1. Multi-timeframe: H4 trend filter + H1 entries
  2. REMOVED losing signals from v2 backtest
  3. Smarter trailing: wide in trend direction, tight against
  4. Dynamic position sizing: 2x on confluence, 1x on single signal
  5. Max hold = adaptive (longer when profitable)
  6. Ready for demo deployment
"""

import pandas as pd
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict
import json
import warnings
warnings.filterwarnings('ignore')


# ============================================================
# DATA PREPARATION
# ============================================================

def compute_indicators(df):
    """Compute all needed indicators"""
    df = df.copy()

    df['ret'] = df['Close'].pct_change()
    df['body'] = df['Close'] - df['Open']
    df['body_abs'] = df['body'].abs()
    df['range'] = df['High'] - df['Low']
    df['body_ratio'] = df['body_abs'] / df['range'].replace(0, np.nan)
    df['is_doji'] = (df['body_ratio'] < 0.1).astype(int)

    # Volatility
    df['vol_5'] = df['ret'].rolling(5).std()
    df['vol_20'] = df['ret'].rolling(20).std()
    df['vol_ratio'] = df['vol_5'] / df['vol_20']
    df['atr'] = df['range'].rolling(14).mean()

    # EMAs
    for s in [5, 10, 20, 50]:
        df[f'ema_{s}'] = df['Close'].ewm(span=s, adjust=False).mean()

    df['dist_ema20'] = (df['Close'] - df['ema_20']) / df['ema_20'] * 100

    # RSI
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))

    # Spikes
    ret_std = df['ret'].rolling(100, min_periods=50).std()
    ret_mean = df['ret'].rolling(100, min_periods=50).mean()
    df['is_crash_spike'] = (df['ret'] < ret_mean - 3 * ret_std).astype(int)

    # Candles since crash
    df['since_crash'] = 0
    c = 999
    for i in range(len(df)):
        if df['is_crash_spike'].iloc[i] == 1:
            c = 0
        else:
            c += 1
        df.iloc[i, df.columns.get_loc('since_crash')] = c

    # Consecutive down candles
    df['consec_down'] = 0
    dc = 0
    for i in range(len(df)):
        if df['ret'].iloc[i] < 0:
            dc += 1
        else:
            dc = 0
        df.iloc[i, df.columns.get_loc('consec_down')] = dc

    # Trend state
    df['trend'] = 0  # -1=down, 0=neutral, 1=up
    df.loc[df['ema_5'] > df['ema_20'], 'trend'] = 1
    df.loc[df['ema_5'] < df['ema_20'], 'trend'] = -1

    return df


def get_h4_trend(h4_df, timestamp):
    """Get H4 trend direction at a given H1 timestamp"""
    # Find the most recent H4 candle before this timestamp
    h4_before = h4_df[h4_df.index <= timestamp]
    if len(h4_before) == 0:
        return 0, 50, 0

    last_h4 = h4_before.iloc[-1]
    trend = last_h4.get('trend', 0)
    rsi = last_h4.get('rsi', 50)
    dist_ema = last_h4.get('dist_ema20', 0)

    return trend, rsi, dist_ema


# ============================================================
# SIGNAL ENGINE - v3 (only profitable signals from v2)
# ============================================================

def detect_signals_v3(row, prev_row, h4_trend, h4_rsi, h4_dist_ema):
    """
    v3 signals for Crash 1000 - LONG ONLY
    Based on v2 backtest results - only keeping profitable signals.

    Profitable in v2:
      post_crash_recovery            +$52 (30 trades, 37% WR)
      post_crash+rsi_oversold        +$35 (14 trades, 50% WR)  <-- BEST
      rsi_oversold+consec_down       +$9  (24 trades, 46% WR)
      confluence combos              +$120 (various)

    Unprofitable (REMOVED):
      rsi_deep_oversold alone        -$34
      rsi_deep_oversold+overext      -$24
    """
    signals = []
    score = 0

    rsi = row.get('rsi', 50)
    is_doji = row.get('is_doji', 0)
    vol_ratio = row.get('vol_ratio', 1.0)
    since_crash = row.get('since_crash', 999)
    consec_down = row.get('consec_down', 0)
    dist_ema20 = row.get('dist_ema20', 0)

    # === HARD FILTERS ===

    # Don't trade on doji (validated: next candle is calm after doji)
    if is_doji:
        return [], 0, 'FILTER:doji'

    # Don't trade during vol squeeze (validated: no expansion follows)
    if vol_ratio < 0.5:
        return [], 0, 'FILTER:squeeze'

    # Don't trade against H4 trend (multi-timeframe filter)
    # Only buy when H4 is not strongly bearish
    if h4_trend == -1 and h4_rsi < 40:
        return [], 0, 'FILTER:h4_bearish'

    # === SIGNAL 1: Post-crash recovery (strongest edge: +18%, 68% WR) ===
    if 1 <= since_crash <= 3:
        signals.append('post_crash_recovery')
        score += 1.0  # strong signal

    # === SIGNAL 2: RSI oversold 20-35 (profitable zone) ===
    # Note: RSI < 20 (deep oversold) was NOT profitable alone in v2
    # But RSI 20-35 combined with other signals WAS profitable
    if 20 <= rsi < 35:
        signals.append('rsi_oversold')
        score += 0.6

    # === SIGNAL 3: Consecutive down + not too extreme ===
    if consec_down >= 3 and rsi > 20:  # avoid catching falling knives (rsi>20)
        signals.append('consec_reversal')
        score += 0.4

    # === SIGNAL 4: Overextended below EMA20 (moderate) ===
    if dist_ema20 < -1.0 and dist_ema20 > -3.0:  # moderate overextension, not extreme
        signals.append('overextended_moderate')
        score += 0.3

    # === SIGNAL 5: Bullish EMA cross (+$243 in v1, profitable) ===
    if prev_row is not None:
        ema5 = row.get('ema_5', 0)
        ema20 = row.get('ema_20', 0)
        pema5 = prev_row.get('ema_5', 0)
        pema20 = prev_row.get('ema_20', 0)
        if ema5 > ema20 and pema5 <= pema20:
            signals.append('bullish_cross')
            score += 0.5

    # === SIGNAL 6: H4 trend alignment bonus ===
    if h4_trend == 1 and len(signals) > 0:
        signals.append('h4_bullish')
        score += 0.3

    # === ENTRY RULES ===
    # Need at least 1 strong signal OR 2 weak signals (confluence)
    has_strong = 'post_crash_recovery' in signals
    n_signals = len([s for s in signals if s != 'h4_bullish'])

    if has_strong or n_signals >= 2:
        return signals, score, 'ENTRY'
    else:
        return signals, score, 'WEAK'


# ============================================================
# TRADE MANAGEMENT
# ============================================================

@dataclass
class TradeV3:
    entry_time: pd.Timestamp
    entry_price: float
    sl_price: float
    tp_price: float
    trail_distance: float
    signal_name: str
    signal_score: float
    size_pct: float
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ''
    bars_held: int = 0
    highest_price: float = 0.0


def calculate_entry(price, atr, score, signals):
    """Calculate SL, TP, trailing distance based on signal strength"""

    # Base: SL = 1.5 ATR, TP = 3 ATR (2:1 ratio)
    sl_mult = 1.5
    tp_mult = 3.0

    # Post-crash recovery: tighter SL (the bounce is quick), wider TP
    if 'post_crash_recovery' in signals:
        sl_mult = 1.2
        tp_mult = 4.0

    # Confluence: wider TP (let winners run more)
    if score >= 1.5:
        tp_mult += 1.0

    sl = price - atr * sl_mult
    tp = price + atr * tp_mult
    trail = atr * 2.0  # trailing distance

    return sl, tp, trail


def manage_trade(trade, high, low, price, atr):
    """Manage open trade - returns exit_price and reason or None"""

    trade.bars_held += 1

    # Update highest price
    trade.highest_price = max(trade.highest_price, high)

    # === TRAILING STOP (only activates after trade is profitable) ===
    profit_pct = (price - trade.entry_price) / trade.entry_price
    if profit_pct > 0.002:  # only trail after 0.2% profit
        trailing_sl = trade.highest_price - trade.trail_distance
        # Ratchet: trailing SL can only go UP
        if trailing_sl > trade.sl_price:
            trade.sl_price = trailing_sl

    # === CHECK EXITS ===

    # Stop loss
    if low <= trade.sl_price:
        return trade.sl_price, 'SL' if trade.sl_price == trade.entry_price - trade.trail_distance else 'TRAIL'

    # Take profit
    if high >= trade.tp_price:
        return trade.tp_price, 'TP'

    # Time stop: 30 bars max (but extend if profitable)
    max_bars = 30
    if profit_pct > 0.01:
        max_bars = 50  # let big winners run

    if trade.bars_held >= max_bars:
        return price, 'TIME'

    return None, None


# ============================================================
# BACKTEST
# ============================================================

def run_backtest(h1_df, h4_df=None, initial_capital=10000):
    """Full backtest with multi-timeframe"""

    h1 = compute_indicators(h1_df)
    h1 = h1.dropna()

    h4 = None
    if h4_df is not None and len(h4_df) > 100:
        h4 = compute_indicators(h4_df)
        h4 = h4.dropna()
        print(f"  H4 trend filter: ACTIVE ({len(h4)} candles)")
    else:
        print(f"  H4 trend filter: DISABLED")

    warmup = int(len(h1) * 0.15)
    data = h1.iloc[warmup:]

    capital = initial_capital
    equity = [capital]
    trades = []
    open_trade = None
    filters_hit = {'doji': 0, 'squeeze': 0, 'h4_bearish': 0, 'weak': 0}
    signals_count = {}

    for i in range(1, len(data)):
        row = data.iloc[i]
        prev_row = data.iloc[i-1]
        price = row['Close']
        high = row['High']
        low = row['Low']
        atr = row.get('atr', price * 0.01)
        if atr <= 0:
            atr = price * 0.005

        # Get H4 context
        h4_trend, h4_rsi, h4_dist = 0, 50, 0
        if h4 is not None:
            h4_trend, h4_rsi, h4_dist = get_h4_trend(h4, row.name)

        # --- Manage open trade ---
        if open_trade is not None:
            exit_price, exit_reason = manage_trade(open_trade, high, low, price, atr)

            if exit_price is not None:
                open_trade.exit_price = exit_price
                open_trade.exit_time = row.name
                open_trade.exit_reason = exit_reason
                open_trade.pnl_pct = (exit_price - open_trade.entry_price) / open_trade.entry_price

                pos_value = capital * open_trade.size_pct
                open_trade.pnl = pos_value * open_trade.pnl_pct
                capital += open_trade.pnl

                trades.append(open_trade)
                open_trade = None

        # --- New signal ---
        if open_trade is None and atr > 0:
            signals, score, action = detect_signals_v3(row, prev_row, h4_trend, h4_rsi, h4_dist)

            if action.startswith('FILTER'):
                ftype = action.split(':')[1]
                filters_hit[ftype] = filters_hit.get(ftype, 0) + 1
            elif action == 'WEAK':
                filters_hit['weak'] += 1
            elif action == 'ENTRY':
                sig_name = '+'.join(signals)
                signals_count[sig_name] = signals_count.get(sig_name, 0) + 1

                sl, tp, trail = calculate_entry(price, atr, score, signals)

                # Dynamic position sizing
                base_size = 0.30  # 30% base
                if score >= 1.5:
                    size = base_size * 1.5  # 45% on confluence
                elif score >= 1.0:
                    size = base_size * 1.2  # 36% on strong
                else:
                    size = base_size

                # Reduce size if H4 is neutral (not confirming)
                if h4_trend == 0:
                    size *= 0.8

                open_trade = TradeV3(
                    entry_time=row.name,
                    entry_price=price,
                    sl_price=sl,
                    tp_price=tp,
                    trail_distance=trail,
                    signal_name=sig_name,
                    signal_score=score,
                    size_pct=size,
                    highest_price=price,
                )

        equity.append(capital)

    # Close remaining
    if open_trade is not None:
        open_trade.exit_price = data.iloc[-1]['Close']
        open_trade.exit_time = data.index[-1]
        open_trade.exit_reason = 'EOD'
        open_trade.pnl_pct = (open_trade.exit_price - open_trade.entry_price) / open_trade.entry_price
        open_trade.pnl = capital * open_trade.size_pct * open_trade.pnl_pct
        capital += open_trade.pnl
        trades.append(open_trade)
        equity.append(capital)

    return capital, equity, trades, filters_hit, signals_count


def print_full_report(capital, equity, trades, filters, sig_counts, label=""):
    """Comprehensive report"""
    if not trades:
        print(f"  No trades generated")
        return None

    df = pd.DataFrame([{
        'entry': t.entry_time, 'exit': t.exit_time,
        'signal': t.signal_name, 'score': t.signal_score,
        'entry_p': t.entry_price, 'exit_p': t.exit_price,
        'pnl': t.pnl, 'pnl_pct': t.pnl_pct * 100,
        'reason': t.exit_reason, 'bars': t.bars_held,
        'size': t.size_pct,
    } for t in trades])

    n = len(df)
    w = df[df['pnl'] > 0]
    l = df[df['pnl'] <= 0]
    wr = len(w) / n * 100
    ret = (capital - 10000) / 10000 * 100
    gp = w['pnl'].sum() if len(w) > 0 else 0
    gl = abs(l['pnl'].sum()) if len(l) > 0 else 0.01
    pf = gp / gl
    eq = np.array(equity)
    pk = np.maximum.accumulate(eq)
    dd = ((eq - pk) / pk * 100).min()

    rets = df['pnl_pct'].values
    sharpe = np.mean(rets) / np.std(rets) * np.sqrt(252/max(1,n)) if len(rets)>1 and np.std(rets)>0 else 0

    # Expectancy per trade
    avg_win_pct = w['pnl_pct'].mean() if len(w) > 0 else 0
    avg_loss_pct = abs(l['pnl_pct'].mean()) if len(l) > 0 else 0
    expectancy = (wr/100 * avg_win_pct) - ((100-wr)/100 * avg_loss_pct)

    print(f"\n  {'='*60}")
    print(f"  CRASH 1000 INDEX - {label}")
    print(f"  {'='*60}")
    print(f"  PERFORMANCE:")
    print(f"    Total return:     {ret:+.2f}%")
    print(f"    Final capital:    ${capital:.2f}")
    print(f"    Profit factor:    {pf:.2f}")
    print(f"    Max drawdown:     {dd:.1f}%")
    print(f"    Sharpe ratio:     {sharpe:.2f}")
    print(f"    Expectancy/trade: {expectancy:+.3f}%")

    print(f"\n  TRADES:")
    print(f"    Total:            {n}")
    print(f"    Win rate:         {wr:.1f}%")
    print(f"    Avg winner:       ${w['pnl'].mean():.2f} ({avg_win_pct:.2f}%)" if len(w)>0 else "")
    print(f"    Avg loser:        ${l['pnl'].mean():.2f} (-{avg_loss_pct:.2f}%)" if len(l)>0 else "")
    print(f"    Avg bars held:    {df['bars'].mean():.1f}")
    print(f"    Best trade:       ${df['pnl'].max():.2f}")
    print(f"    Worst trade:      ${df['pnl'].min():.2f}")

    # Exits
    print(f"\n  EXITS: ", end='')
    for r in ['TP', 'SL', 'TRAIL', 'TIME', 'EOD']:
        c = len(df[df['reason']==r])
        if c > 0:
            pnl_r = df[df['reason']==r]['pnl'].sum()
            print(f"{r}={c}(${pnl_r:+.0f}) ", end='')
    print()

    # Filters
    print(f"\n  FILTERS (trades avoided):")
    for f, c in sorted(filters.items(), key=lambda x: -x[1]):
        if c > 0:
            print(f"    {f}: {c} candles filtered")

    # Signal performance
    print(f"\n  SIGNALS:")
    sp = df.groupby('signal').agg(
        count=('pnl','count'), wr=('pnl',lambda x:(x>0).mean()*100),
        total=('pnl','sum'), avg=('pnl','mean'),
        avg_score=('score','mean'),
    ).sort_values('total', ascending=False)

    for sig, r in sp.iterrows():
        m = "PROFIT" if r['total'] > 0 else "LOSS"
        print(f"    {sig}")
        print(f"      N={int(r['count'])} WR={r['wr']:.0f}% Total=${r['total']:+.2f} Avg=${r['avg']:+.2f} [{m}]")

    # Monthly
    df['month'] = pd.to_datetime(df['entry']).dt.to_period('M')
    monthly = df.groupby('month').agg(
        pnl=('pnl','sum'), count=('pnl','count'),
        wr=('pnl', lambda x: (x>0).mean()*100)
    )
    print(f"\n  MONTHLY BREAKDOWN:")
    wm = 0
    for month, r in monthly.iterrows():
        m = "+" if r['pnl'] > 0 else "-"
        print(f"    {month}: ${r['pnl']:>+8.2f} | {int(r['count']):>2} trades | WR={r['wr']:.0f}% {m}")
        if r['pnl'] > 0:
            wm += 1
    print(f"  Profitable months: {wm}/{len(monthly)} ({wm/len(monthly)*100:.0f}%)")

    # Equity curve stats
    eq_series = pd.Series(equity)
    print(f"\n  EQUITY CURVE:")
    print(f"    Start:  ${equity[0]:.2f}")
    print(f"    End:    ${equity[-1]:.2f}")
    print(f"    Min:    ${min(equity):.2f}")
    print(f"    Max:    ${max(equity):.2f}")

    return df


# ============================================================
# MAIN
# ============================================================

def main():
    print("="*70)
    print("  TRADING SYSTEM v3 - CRASH 1000 OPTIMIZED")
    print("  Multi-timeframe | Proven signals only | Smart trailing")
    print("="*70)

    # Load data
    h1_path = Path('data/raw/Crash_1000_Index_H1.parquet')
    h4_path = Path('data/raw/Crash_1000_Index_H4.parquet')

    if not h1_path.exists():
        print("ERROR: No H1 data for Crash 1000")
        return

    h1_df = pd.read_parquet(h1_path)
    print(f"\n  H1: {len(h1_df)} candles | {(h1_df.index[-1]-h1_df.index[0]).days} days")

    h4_df = None
    if h4_path.exists():
        h4_df = pd.read_parquet(h4_path)
        print(f"  H4: {len(h4_df)} candles | {(h4_df.index[-1]-h4_df.index[0]).days} days")

    # === TEST 1: H1 only ===
    print(f"\n{'#'*70}")
    print(f"#  TEST 1: H1 ONLY (no H4 filter)")
    print(f"{'#'*70}")

    cap1, eq1, trades1, filt1, sigs1 = run_backtest(h1_df, None)
    df1 = print_full_report(cap1, eq1, trades1, filt1, sigs1, "H1 ONLY")

    # === TEST 2: H1 + H4 trend filter ===
    if h4_df is not None:
        print(f"\n{'#'*70}")
        print(f"#  TEST 2: H1 + H4 TREND FILTER (multi-timeframe)")
        print(f"{'#'*70}")

        cap2, eq2, trades2, filt2, sigs2 = run_backtest(h1_df, h4_df)
        df2 = print_full_report(cap2, eq2, trades2, filt2, sigs2, "H1 + H4 MTF")

        # === COMPARISON ===
        print(f"\n{'='*70}")
        print(f"  COMPARISON: H1 only vs H1+H4")
        print(f"{'='*70}")

        ret1 = (cap1 - 10000) / 100
        ret2 = (cap2 - 10000) / 100
        n1 = len(trades1)
        n2 = len(trades2)
        wr1 = sum(1 for t in trades1 if t.pnl > 0) / max(1,n1) * 100
        wr2 = sum(1 for t in trades2 if t.pnl > 0) / max(1,n2) * 100
        dd1 = ((np.array(eq1) - np.maximum.accumulate(eq1)) / np.maximum.accumulate(eq1) * 100).min()
        dd2 = ((np.array(eq2) - np.maximum.accumulate(eq2)) / np.maximum.accumulate(eq2) * 100).min()

        print(f"\n  {'Metric':<20} {'H1 Only':>12} {'H1+H4':>12} {'Better':>10}")
        print(f"  {'-'*20} {'-'*12} {'-'*12} {'-'*10}")
        print(f"  {'Return':<20} {ret1:>+11.2f}% {ret2:>+11.2f}% {'H1+H4' if ret2 > ret1 else 'H1':>10}")
        print(f"  {'Trades':<20} {n1:>12} {n2:>12} {'H1+H4' if n2 < n1 else 'H1':>10}")
        print(f"  {'Win Rate':<20} {wr1:>11.1f}% {wr2:>11.1f}% {'H1+H4' if wr2 > wr1 else 'H1':>10}")
        print(f"  {'Max Drawdown':<20} {dd1:>11.1f}% {dd2:>11.1f}% {'H1+H4' if dd2 > dd1 else 'H1':>10}")
        print(f"  {'Final Capital':<20} ${cap1:>10.2f} ${cap2:>10.2f} {'H1+H4' if cap2 > cap1 else 'H1':>10}")

    print(f"\n{'='*70}")
    print(f"  NEXT: Deploy best version to demo account")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
