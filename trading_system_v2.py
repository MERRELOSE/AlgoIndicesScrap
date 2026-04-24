#!/usr/bin/env python3
"""
BEHAVIOR-BASED TRADING SYSTEM v2 - OPTIMIZED
=============================================
Changes from v1 based on backtest results:
  1. REMOVED losing signals (high_vol_overbought_sell, bearish_ema_cross)
  2. LONG-ONLY on Crash indices (proven edge)
  3. Require CONFLUENCE (2+ signals) for stronger entries
  4. Better SL/TP: wider TP (trending markets), trailing stop
  5. Filter: no trade during doji or vol squeeze
  6. Reduced trade frequency = higher quality
"""

import pandas as pd
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import warnings
warnings.filterwarnings('ignore')


@dataclass
class Trade:
    entry_time: pd.Timestamp
    direction: str
    entry_price: float
    sl_price: float
    tp_price: float
    trailing_sl: float  # trailing stop
    signal_name: str
    signal_score: float
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ''
    bars_held: int = 0


def prepare_data(df):
    """Compute indicators"""
    df = df.copy()

    df['ret'] = df['Close'].pct_change()
    df['body'] = df['Close'] - df['Open']
    df['body_abs'] = df['body'].abs()
    df['range'] = df['High'] - df['Low']
    df['body_ratio'] = df['body_abs'] / df['range'].replace(0, np.nan)
    df['is_doji'] = (df['body_ratio'] < 0.1).astype(int)
    df['is_bullish'] = (df['Close'] > df['Open']).astype(int)

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
    df['is_boom_spike'] = (df['ret'] > ret_mean + 3 * ret_std).astype(int)

    df['candles_since_crash'] = 0
    df['candles_since_boom'] = 0
    cc = 999
    bc = 999
    for i in range(len(df)):
        if df['is_crash_spike'].iloc[i] == 1:
            cc = 0
        else:
            cc += 1
        df.iloc[i, df.columns.get_loc('candles_since_crash')] = cc
        if df['is_boom_spike'].iloc[i] == 1:
            bc = 0
        else:
            bc += 1
        df.iloc[i, df.columns.get_loc('candles_since_boom')] = bc

    # Consecutive
    df['consec_down'] = 0
    dc = 0
    for i in range(len(df)):
        if df['ret'].iloc[i] < 0:
            dc += 1
        else:
            dc = 0
        df.iloc[i, df.columns.get_loc('consec_down')] = dc

    return df


def get_signals_v2(row, prev_row, index_type):
    """
    v2: Only PROVEN PROFITABLE signals from v1 backtest results.
    Returns: list of (name, direction, strength)
    """
    signals = []

    rsi = row.get('rsi', 50)
    is_doji = row.get('is_doji', 0)
    vol_ratio = row.get('vol_ratio', 1.0)
    candles_since_crash = row.get('candles_since_crash', 999)
    candles_since_boom = row.get('candles_since_boom', 999)
    dist_ema20 = row.get('dist_ema20', 0)
    consec_down = row.get('consec_down', 0)

    # === FILTERS (block trading) ===
    if is_doji:
        return [('FILTER_DOJI', 'SKIP', 1.0)]

    if vol_ratio < 0.5:
        return [('FILTER_SQUEEZE', 'SKIP', 1.0)]

    # === CRASH INDEX - LONG ONLY (proven profitable) ===
    if index_type == 'crash':

        # Signal 1: Post-crash recovery (BEST signal: +$246, 68% win)
        if 1 <= candles_since_crash <= 3:
            signals.append(('post_crash_recovery', 'long', 1.0))

        # Signal 2: RSI oversold buy (profitable: +$439 on C1000, +$67 on C500)
        if rsi < 20:
            signals.append(('rsi_deep_oversold', 'long', 0.8))
        elif rsi < 30:
            signals.append(('rsi_oversold', 'long', 0.5))

        # Signal 3: Bullish EMA cross (+$243 on C1000, +$172 on C500)
        if prev_row is not None:
            ema5 = row.get('ema_5', 0)
            ema20 = row.get('ema_20', 0)
            pema5 = prev_row.get('ema_5', 0)
            pema20 = prev_row.get('ema_20', 0)
            if ema5 > ema20 and pema5 <= pema20:
                signals.append(('bullish_cross', 'long', 0.6))

        # Signal 4: Price far below EMA20 (overextended = bounce)
        if dist_ema20 < -1.5:
            signals.append(('overextended_down', 'long', 0.5))

        # Signal 5: Multiple consecutive down candles (reversal due)
        if consec_down >= 4:
            signals.append(('consec_down_reversal', 'long', 0.4))

    # === BOOM INDEX - mixed but LONG on dips works ===
    elif index_type == 'boom':

        # Post-boom correction: SHORT (profitable +$171 in v1)
        if 1 <= candles_since_boom <= 3:
            signals.append(('post_boom_correction', 'short', 0.9))

        # RSI oversold = BUY (Boom has upward bias from spikes)
        if rsi < 20:
            signals.append(('rsi_deep_oversold', 'long', 0.7))
        elif rsi < 30:
            signals.append(('rsi_oversold', 'long', 0.5))

        # Bearish EMA cross was profitable for Boom (+$319 in v1)
        if prev_row is not None:
            ema5 = row.get('ema_5', 0)
            ema20 = row.get('ema_20', 0)
            pema5 = prev_row.get('ema_5', 0)
            pema20 = prev_row.get('ema_20', 0)
            if ema5 < ema20 and pema5 >= pema20:
                signals.append(('bearish_cross', 'short', 0.6))
            elif ema5 > ema20 and pema5 <= pema20:
                signals.append(('bullish_cross', 'long', 0.5))

    # === VOLATILITY - both directions, RSI + EMA ===
    elif index_type == 'volatility':

        # RSI oversold BUY (BEST signal: +$430 on Vol25)
        if rsi < 25:
            signals.append(('rsi_oversold', 'long', 0.7))

        # Bullish EMA cross (+$235 on Vol25)
        if prev_row is not None:
            ema5 = row.get('ema_5', 0)
            ema20 = row.get('ema_20', 0)
            pema5 = prev_row.get('ema_5', 0)
            pema20 = prev_row.get('ema_20', 0)
            if ema5 > ema20 and pema5 <= pema20:
                signals.append(('bullish_cross', 'long', 0.6))
            # Bearish cross was profitable on Vol25 too (+$160)
            elif ema5 < ema20 and pema5 >= pema20:
                signals.append(('bearish_cross', 'short', 0.5))

        # Overextended down = buy
        if dist_ema20 < -2.0:
            signals.append(('overextended_down', 'long', 0.5))

    return signals


def resolve_v2(signals):
    """Resolve signals with confluence requirement"""
    if not signals:
        return None

    # Check filters
    for name, direction, _ in signals:
        if direction == 'SKIP':
            return None

    # Separate by direction
    longs = [(n, s) for n, d, s in signals if d == 'long']
    shorts = [(n, s) for n, d, s in signals if d == 'short']

    long_score = sum(s for _, s in longs)
    short_score = sum(s for _, s in shorts)

    # For single very strong signals (post_crash_recovery, post_boom_correction)
    # allow trade without confluence
    has_strong = any(s >= 0.9 for _, _, s in signals if _ != 'SKIP')

    # Minimum threshold: either 1 strong signal or 2+ normal signals
    min_score = 0.5

    if long_score > short_score and long_score >= min_score:
        n_sigs = len(longs)
        if n_sigs >= 2 or has_strong:
            names = '+'.join(n for n, _ in longs)
            return ('long', names, long_score, n_sigs)

    if short_score > long_score and short_score >= min_score:
        n_sigs = len(shorts)
        if n_sigs >= 2 or has_strong:
            names = '+'.join(n for n, _ in shorts)
            return ('short', names, short_score, n_sigs)

    return None


def backtest_v2(df_raw, index_type, symbol):
    """Backtest with v2 optimized signals + trailing stop"""
    df = prepare_data(df_raw)
    df = df.dropna()

    warmup = int(len(df) * 0.15)
    data = df.iloc[warmup:]

    capital = 10000.0
    equity = [capital]
    trades = []
    open_trade = None
    position_pct = 0.30  # 30% of capital per trade

    for i in range(1, len(data)):
        row = data.iloc[i]
        prev_row = data.iloc[i-1]
        price = row['Close']
        high = row['High']
        low = row['Low']
        atr = row.get('atr', price * 0.01)

        # --- Manage open trade ---
        if open_trade is not None:
            t = open_trade
            t.bars_held += 1

            # Update trailing stop
            if t.direction == 'long':
                new_trail = price - atr * 2.0
                if new_trail > t.trailing_sl:
                    t.trailing_sl = new_trail

                # Check exits
                effective_sl = max(t.sl_price, t.trailing_sl)

                if low <= effective_sl:
                    t.exit_price = effective_sl
                    t.exit_reason = 'TRAIL' if effective_sl == t.trailing_sl else 'SL'
                elif high >= t.tp_price:
                    t.exit_price = t.tp_price
                    t.exit_reason = 'TP'
                elif t.bars_held >= 20:  # max hold time
                    t.exit_price = price
                    t.exit_reason = 'TIME'

            else:  # short
                new_trail = price + atr * 2.0
                if new_trail < t.trailing_sl:
                    t.trailing_sl = new_trail

                effective_sl = min(t.sl_price, t.trailing_sl)

                if high >= effective_sl:
                    t.exit_price = effective_sl
                    t.exit_reason = 'TRAIL' if effective_sl == t.trailing_sl else 'SL'
                elif low <= t.tp_price:
                    t.exit_price = t.tp_price
                    t.exit_reason = 'TP'
                elif t.bars_held >= 20:
                    t.exit_price = price
                    t.exit_reason = 'TIME'

            if t.exit_price is not None:
                t.exit_time = row.name
                if t.direction == 'long':
                    t.pnl_pct = (t.exit_price - t.entry_price) / t.entry_price
                else:
                    t.pnl_pct = (t.entry_price - t.exit_price) / t.entry_price

                pos_value = capital * position_pct
                t.pnl = pos_value * t.pnl_pct
                capital += t.pnl
                trades.append(t)
                open_trade = None

        # --- New signals ---
        if open_trade is None:
            sigs = get_signals_v2(row, prev_row, index_type)
            result = resolve_v2(sigs)

            if result is not None:
                direction, names, score, n_sigs = result

                # Adaptive SL/TP based on ATR
                if direction == 'long':
                    sl = price - atr * 2.0
                    tp = price + atr * 4.0  # 2:1 reward ratio
                    trail = sl
                else:
                    sl = price + atr * 2.0
                    tp = price - atr * 4.0
                    trail = sl

                # Stronger signals get wider TP
                if score >= 1.5:  # confluence
                    if direction == 'long':
                        tp = price + atr * 5.0
                    else:
                        tp = price - atr * 5.0

                open_trade = Trade(
                    entry_time=row.name,
                    direction=direction,
                    entry_price=price,
                    sl_price=sl,
                    tp_price=tp,
                    trailing_sl=trail,
                    signal_name=names,
                    signal_score=score,
                )

        equity.append(capital)

    # Close remaining
    if open_trade is not None:
        t = open_trade
        t.exit_price = data.iloc[-1]['Close']
        t.exit_time = data.index[-1]
        t.exit_reason = 'EOD'
        if t.direction == 'long':
            t.pnl_pct = (t.exit_price - t.entry_price) / t.entry_price
        else:
            t.pnl_pct = (t.entry_price - t.exit_price) / t.entry_price
        t.pnl = capital * position_pct * t.pnl_pct
        capital += t.pnl
        trades.append(t)
        equity.append(capital)

    return capital, equity, trades


def print_report(symbol, capital, equity, trades):
    """Print results"""
    if not trades:
        print(f"  {symbol}: No trades")
        return

    df = pd.DataFrame([{
        'entry': t.entry_time, 'exit': t.exit_time,
        'dir': t.direction, 'signal': t.signal_name,
        'score': t.signal_score, 'pnl': t.pnl,
        'pnl_pct': t.pnl_pct * 100, 'reason': t.exit_reason,
        'bars': t.bars_held,
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

    sharpe = 0
    if len(df) > 2:
        r = df['pnl_pct'].values
        sharpe = np.mean(r) / np.std(r) * np.sqrt(252 / max(1, n)) if np.std(r) > 0 else 0

    print(f"\n  {'='*60}")
    print(f"  {symbol}")
    print(f"  {'='*60}")
    print(f"  Trades:         {n}")
    print(f"  Win rate:       {wr:.1f}%")
    print(f"  Profit factor:  {pf:.2f}")
    print(f"  Return:         {ret:+.2f}%")
    print(f"  Final:          ${capital:.2f}")
    print(f"  Max drawdown:   {dd:.1f}%")
    print(f"  Sharpe:         {sharpe:.2f}")
    if len(w) > 0:
        print(f"  Avg win:        ${w['pnl'].mean():.2f} ({w['pnl_pct'].mean():.2f}%)")
    if len(l) > 0:
        print(f"  Avg loss:       ${l['pnl'].mean():.2f} ({l['pnl_pct'].mean():.2f}%)")
    print(f"  Avg bars held:  {df['bars'].mean():.1f}")

    # By direction
    for d in ['long', 'short']:
        dt = df[df['dir'] == d]
        if len(dt) > 0:
            dwr = len(dt[dt['pnl'] > 0]) / len(dt) * 100
            dpnl = dt['pnl'].sum()
            print(f"  {d.upper():5s}: {len(dt)} trades | WR: {dwr:.0f}% | PnL: ${dpnl:+.2f}")

    # Exit reasons
    print(f"\n  Exits: ", end='')
    for r in ['TP', 'SL', 'TRAIL', 'TIME', 'EOD']:
        c = len(df[df['reason'] == r])
        if c > 0:
            print(f"{r}={c} ", end='')
    print()

    # Signal performance
    print(f"\n  Signals:")
    sp = df.groupby('signal').agg(
        count=('pnl', 'count'),
        wr=('pnl', lambda x: (x > 0).mean() * 100),
        total=('pnl', 'sum'),
        avg=('pnl', 'mean'),
    ).sort_values('total', ascending=False)

    for sig, r in sp.iterrows():
        m = "+" if r['total'] > 0 else "-"
        print(f"    {sig:<45} N={int(r['count']):>3} WR={r['wr']:>5.1f}% Total=${r['total']:>8.2f} Avg=${r['avg']:>6.2f} {m}")

    # Monthly
    df['month'] = pd.to_datetime(df['entry']).dt.to_period('M')
    monthly = df.groupby('month')['pnl'].agg(['sum', 'count'])
    print(f"\n  Monthly:")
    wm = 0
    for month, r in monthly.iterrows():
        m = "+" if r['sum'] > 0 else "-"
        print(f"    {month}: ${r['sum']:>8.2f} ({int(r['count'])} trades) {m}")
        if r['sum'] > 0:
            wm += 1
    print(f"  Profitable months: {wm}/{len(monthly)} ({wm/len(monthly)*100:.0f}%)")

    return df


def main():
    print("="*70)
    print("  TRADING SYSTEM v2 - OPTIMIZED")
    print("  Long-biased | Confluence required | Trailing stops")
    print("="*70)

    indices = [
        ('Boom 1000 Index', 'boom'),
        ('Crash 1000 Index', 'crash'),
        ('Crash 500 Index', 'crash'),
        ('Volatility 25 Index', 'volatility'),
    ]

    results = {}

    for symbol, itype in indices:
        safe = symbol.replace(' ', '_')
        fpath = Path(f'data/raw/{safe}_H1.parquet')
        if not fpath.exists():
            continue

        df = pd.read_parquet(fpath)
        print(f"\n{'#'*70}")
        print(f"#  {symbol} ({itype.upper()}) - {len(df)} candles")
        print(f"{'#'*70}")

        capital, equity, trades = backtest_v2(df, itype, symbol)
        tdf = print_report(symbol, capital, equity, trades)
        results[symbol] = {'capital': capital, 'equity': equity, 'trades': trades, 'df': tdf}

    # Final comparison
    print(f"\n\n{'#'*70}")
    print(f"#  v2 FINAL COMPARISON")
    print(f"{'#'*70}")

    print(f"\n  {'Symbol':<25} {'Return':>8} {'Trades':>7} {'WR':>6} {'PF':>6} {'MaxDD':>7} {'Sharpe':>7} {'Capital':>10}")
    print(f"  {'-'*25} {'-'*8} {'-'*7} {'-'*6} {'-'*6} {'-'*7} {'-'*7} {'-'*10}")

    total_cap = 0
    for sym, r in results.items():
        cap = r['capital']
        total_cap += cap
        t = r['df']
        if t is None:
            continue
        n = len(t)
        wr = len(t[t['pnl'] > 0]) / n * 100 if n > 0 else 0
        gp = t[t['pnl'] > 0]['pnl'].sum() if len(t[t['pnl'] > 0]) > 0 else 0
        gl = abs(t[t['pnl'] <= 0]['pnl'].sum()) if len(t[t['pnl'] <= 0]) > 0 else 0.01
        pf = gp / gl
        eq = np.array(r['equity'])
        pk = np.maximum.accumulate(eq)
        dd = ((eq - pk) / pk * 100).min()
        ret = (cap - 10000) / 10000 * 100
        rets = t['pnl_pct'].values
        sh = np.mean(rets) / np.std(rets) * np.sqrt(252 / max(1, n)) if len(rets) > 1 and np.std(rets) > 0 else 0

        print(f"  {sym:<25} {ret:>+7.1f}% {n:>7} {wr:>5.1f}% {pf:>6.2f} {dd:>6.1f}% {sh:>7.2f} ${cap:>9.2f}")

    invested = 10000 * len(results)
    print(f"\n  Combined: ${total_cap:.2f} from ${invested} ({(total_cap/invested-1)*100:+.1f}%)")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
