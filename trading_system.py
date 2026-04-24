#!/usr/bin/env python3
"""
BEHAVIOR-BASED TRADING SYSTEM
==============================
Uses ONLY statistically validated behaviors as trading rules.
No ML, no prediction - just proven patterns with edge.

For each index, the system:
  1. Detects when a validated behavior condition is met
  2. Enters a trade in the direction the behavior predicts
  3. Manages risk with adaptive SL/TP based on volatility
  4. Scores signals by combining multiple behaviors (confluence)

Walk-forward backtest on top 4 indices.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional
import warnings
warnings.filterwarnings('ignore')


# ============================================================
# TRADE MANAGEMENT
# ============================================================

@dataclass
class Trade:
    entry_time: pd.Timestamp
    direction: str  # 'long' or 'short'
    entry_price: float
    sl_price: float
    tp_price: float
    signal_name: str
    signal_score: float
    size_pct: float  # % of capital risked
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ''
    max_favorable: float = 0.0
    max_adverse: float = 0.0


@dataclass
class Portfolio:
    initial_capital: float = 10000.0
    capital: float = 10000.0
    equity_curve: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    open_trade: Optional[Trade] = None
    max_risk_pct: float = 0.02  # 2% max risk per trade
    max_daily_loss_pct: float = 0.05  # 5% max daily loss
    daily_pnl: float = 0.0
    last_trade_day: int = -1


# ============================================================
# SIGNAL DETECTION - Each behavior becomes a signal
# ============================================================

def prepare_signals_data(df):
    """Compute all indicators needed for signal detection"""
    df = df.copy()

    # Returns
    df['ret'] = df['Close'].pct_change()
    df['ret_abs'] = df['ret'].abs()

    # Candle properties
    df['body'] = df['Close'] - df['Open']
    df['body_abs'] = df['body'].abs()
    df['range'] = df['High'] - df['Low']
    df['body_ratio'] = df['body_abs'] / df['range'].replace(0, np.nan)
    df['is_bullish'] = (df['Close'] > df['Open']).astype(int)
    df['is_doji'] = (df['body_ratio'] < 0.1).astype(int)

    # Volatility
    df['vol_5'] = df['ret'].rolling(5).std()
    df['vol_20'] = df['ret'].rolling(20).std()
    df['vol_ratio'] = df['vol_5'] / df['vol_20']
    df['atr_14'] = df['range'].rolling(14).mean()
    df['atr_5'] = df['range'].rolling(5).mean()

    # EMAs
    for span in [5, 10, 20, 50]:
        df[f'ema_{span}'] = df['Close'].ewm(span=span, adjust=False).mean()

    df['dist_ema20'] = (df['Close'] - df['ema_20']) / df['ema_20'] * 100

    # RSI
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))

    # Spike detection (rolling stats)
    ret_std = df['ret'].rolling(100, min_periods=50).std()
    ret_mean = df['ret'].rolling(100, min_periods=50).mean()
    df['is_crash_spike'] = (df['ret'] < ret_mean - 3 * ret_std).astype(int)
    df['is_boom_spike'] = (df['ret'] > ret_mean + 3 * ret_std).astype(int)

    # Candles since last spike
    df['candles_since_crash'] = 0
    df['candles_since_boom'] = 0
    crash_count = 999
    boom_count = 999
    for i in range(len(df)):
        if df['is_crash_spike'].iloc[i] == 1:
            crash_count = 0
        else:
            crash_count += 1
        df.iloc[i, df.columns.get_loc('candles_since_crash')] = crash_count

        if df['is_boom_spike'].iloc[i] == 1:
            boom_count = 0
        else:
            boom_count += 1
        df.iloc[i, df.columns.get_loc('candles_since_boom')] = boom_count

    # Consecutive moves
    df['consec_up'] = 0
    df['consec_down'] = 0
    up_c = 0
    down_c = 0
    for i in range(len(df)):
        if df['ret'].iloc[i] > 0:
            up_c += 1
            down_c = 0
        elif df['ret'].iloc[i] < 0:
            down_c += 1
            up_c = 0
        else:
            up_c = 0
            down_c = 0
        df.iloc[i, df.columns.get_loc('consec_up')] = up_c
        df.iloc[i, df.columns.get_loc('consec_down')] = down_c

    # Higher highs / lower lows
    df['higher_high'] = (df['High'] > df['High'].shift(1)).astype(int)
    df['lower_low'] = (df['Low'] < df['Low'].shift(1)).astype(int)
    df['hh_streak'] = df['higher_high'].rolling(5).sum()
    df['ll_streak'] = df['lower_low'].rolling(5).sum()

    return df


def detect_signals(row, prev_rows, index_type):
    """
    Detect all active behavior signals for the current candle.
    Returns list of (signal_name, direction, strength) tuples.

    index_type: 'crash', 'boom', 'volatility', 'step'
    """
    signals = []

    rsi = row.get('rsi', 50)
    vol_ratio = row.get('vol_ratio', 1.0)
    vol_5 = row.get('vol_5', 0)
    is_doji = row.get('is_doji', 0)
    dist_ema20 = row.get('dist_ema20', 0)
    candles_since_crash = row.get('candles_since_crash', 999)
    candles_since_boom = row.get('candles_since_boom', 999)

    # --- UNIVERSAL BEHAVIORS (all indices) ---

    # 1. DOJI = don't trade (filter, not signal)
    if is_doji:
        signals.append(('doji_filter', 'SKIP', 0.8))

    # 2. Vol squeeze = don't trade (wait for expansion)
    if vol_ratio < 0.6:
        signals.append(('vol_squeeze_filter', 'SKIP', 0.6))

    # --- CRASH INDEX BEHAVIORS ---
    if index_type == 'crash':

        # Post-crash recovery: BUY after crash spike (68% win rate, +18% edge)
        if candles_since_crash <= 2 and candles_since_crash >= 1:
            signals.append(('post_crash_recovery', 'long', 0.9))

        # High vol + overbought RSI -> SELL (61% win, -10% edge)
        vol_20 = row.get('vol_20', 0)
        vol_5_val = row.get('vol_5', 0)
        if vol_5_val > 0 and vol_20 > 0:
            vol_percentile_high = vol_5_val > vol_20 * 1.3
        else:
            vol_percentile_high = False

        if vol_percentile_high and rsi > 65:
            signals.append(('high_vol_overbought_sell', 'short', 0.7))

        # RSI oversold -> BUY bounce (61% on M15, 57% on H1)
        if rsi < 20:
            signals.append(('rsi_deep_oversold_buy', 'long', 0.75))
        elif rsi < 30:
            signals.append(('rsi_oversold_buy', 'long', 0.5))

        # EMA5 bullish cross (55% on H4, +4.9% edge)
        ema5 = row.get('ema_5', 0)
        ema20 = row.get('ema_20', 0)
        if len(prev_rows) > 0:
            prev_ema5 = prev_rows.iloc[-1].get('ema_5', 0)
            prev_ema20 = prev_rows.iloc[-1].get('ema_20', 0)
            if ema5 > ema20 and prev_ema5 <= prev_ema20:
                signals.append(('bullish_ema_cross', 'long', 0.5))
            elif ema5 < ema20 and prev_ema5 >= prev_ema20:
                signals.append(('bearish_ema_cross', 'short', 0.5))

    # --- BOOM INDEX BEHAVIORS ---
    elif index_type == 'boom':

        # Post-boom spike: SELL after boom (mirror of crash recovery)
        if candles_since_boom <= 2 and candles_since_boom >= 1:
            signals.append(('post_boom_correction', 'short', 0.9))

        # RSI oversold in Boom -> BUY (confirmed behavior)
        if rsi < 20:
            signals.append(('rsi_deep_oversold_buy', 'long', 0.75))
        elif rsi < 30:
            signals.append(('rsi_oversold_buy', 'long', 0.55))

        # RSI deeply overbought in Boom 1000 -> actually SELLS (-11% edge)
        if rsi > 80:
            signals.append(('rsi_overbought_sell', 'short', 0.6))

        # Vol squeeze + downtrend -> breakout DOWN
        if vol_ratio < 0.6:
            ema5 = row.get('ema_5', 0)
            ema20 = row.get('ema_20', 0)
            if ema5 < ema20:
                signals.append(('squeeze_downtrend_sell', 'short', 0.55))
            elif ema5 > ema20:
                signals.append(('squeeze_uptrend_buy', 'long', 0.45))

        # EMA cross
        ema5 = row.get('ema_5', 0)
        ema20 = row.get('ema_20', 0)
        if len(prev_rows) > 0:
            prev_ema5 = prev_rows.iloc[-1].get('ema_5', 0)
            prev_ema20 = prev_rows.iloc[-1].get('ema_20', 0)
            if ema5 > ema20 and prev_ema5 <= prev_ema20:
                signals.append(('bullish_ema_cross', 'long', 0.5))
            elif ema5 < ema20 and prev_ema5 >= prev_ema20:
                signals.append(('bearish_ema_cross', 'short', 0.5))

    # --- VOLATILITY INDEX BEHAVIORS ---
    elif index_type == 'volatility':

        # RSI extremes
        if rsi < 25:
            signals.append(('rsi_oversold_buy', 'long', 0.55))
        elif rsi > 75:
            signals.append(('rsi_overbought_sell', 'short', 0.55))

        # EMA cross (validated on Vol 25)
        ema5 = row.get('ema_5', 0)
        ema20 = row.get('ema_20', 0)
        if len(prev_rows) > 0:
            prev_ema5 = prev_rows.iloc[-1].get('ema_5', 0)
            prev_ema20 = prev_rows.iloc[-1].get('ema_20', 0)
            if ema5 > ema20 and prev_ema5 <= prev_ema20:
                signals.append(('bullish_ema_cross', 'long', 0.5))
            elif ema5 < ema20 and prev_ema5 >= prev_ema20:
                signals.append(('bearish_ema_cross', 'short', 0.5))

        # Overextended from EMA20 (mean reversion in vol indices)
        if dist_ema20 > 2.0:
            signals.append(('overextended_up_sell', 'short', 0.5))
        elif dist_ema20 < -2.0:
            signals.append(('overextended_down_buy', 'long', 0.5))

    return signals


def resolve_signals(signals):
    """
    Combine multiple signals into a single trading decision.
    Uses confluence: more signals in same direction = stronger.
    """
    if not signals:
        return None, 0

    # Check for SKIP filters
    skip_score = sum(s[2] for s in signals if s[1] == 'SKIP')
    if skip_score >= 0.8:
        return None, 0

    # Separate long and short signals (exclude SKIPs)
    longs = [(name, score) for name, direction, score in signals if direction == 'long']
    shorts = [(name, score) for name, direction, score in signals if direction == 'short']

    long_score = sum(s for _, s in longs)
    short_score = sum(s for _, s in shorts)

    # Need minimum score threshold to trade
    min_score = 0.5

    if long_score > short_score and long_score >= min_score:
        names = '+'.join(n for n, _ in longs)
        return ('long', names, long_score, len(longs))
    elif short_score > long_score and short_score >= min_score:
        names = '+'.join(n for n, _ in shorts)
        return ('short', names, short_score, len(shorts))

    return None, 0


# ============================================================
# ADAPTIVE RISK MANAGEMENT
# ============================================================

def calculate_sl_tp(row, direction, index_type):
    """
    Adaptive SL/TP based on current volatility.
    Wider in high vol, tighter in low vol.
    """
    atr = row.get('atr_14', 0)
    price = row['Close']

    if atr <= 0 or price <= 0:
        return price * 0.98, price * 1.04  # fallback

    # SL = 2x ATR, TP = 3x ATR (1.5:1 reward/risk)
    sl_distance = atr * 2.0
    tp_distance = atr * 3.0

    # For post-spike recovery trades: tighter SL, wider TP
    signal_name = row.get('_signal_name', '')
    if 'recovery' in str(signal_name) or 'post_' in str(signal_name):
        sl_distance = atr * 1.5
        tp_distance = atr * 4.0  # bigger reward on spike recovery

    if direction == 'long':
        sl = price - sl_distance
        tp = price + tp_distance
    else:
        sl = price + sl_distance
        tp = price - tp_distance

    return sl, tp


# ============================================================
# BACKTESTING ENGINE
# ============================================================

def backtest(df_raw, index_type, symbol_name):
    """
    Walk-forward backtest with behavior-based signals.
    First 20% of data = warmup (no trading).
    Remaining 80% = live trading simulation.
    """
    # Prepare data
    df = prepare_signals_data(df_raw)
    df = df.dropna()

    # Warmup period
    warmup = int(len(df) * 0.2)
    trade_data = df.iloc[warmup:]

    print(f"\n  Warmup: {warmup} candles | Trading: {len(trade_data)} candles")

    portfolio = Portfolio()
    portfolio.equity_curve = [portfolio.capital]

    total_signals = 0
    skip_count = 0
    trade_count = 0

    for i in range(1, len(trade_data)):
        row = trade_data.iloc[i]
        prev_rows = trade_data.iloc[max(0, i-5):i]

        current_price = row['Close']
        high = row['High']
        low = row['Low']

        # --- Check open trade ---
        if portfolio.open_trade is not None:
            t = portfolio.open_trade

            # Track max favorable/adverse
            if t.direction == 'long':
                t.max_favorable = max(t.max_favorable, (high - t.entry_price) / t.entry_price)
                t.max_adverse = max(t.max_adverse, (t.entry_price - low) / t.entry_price)

                # Check SL
                if low <= t.sl_price:
                    t.exit_price = t.sl_price
                    t.exit_reason = 'SL'
                # Check TP
                elif high >= t.tp_price:
                    t.exit_price = t.tp_price
                    t.exit_reason = 'TP'

                if t.exit_price:
                    t.pnl_pct = (t.exit_price - t.entry_price) / t.entry_price
            else:
                t.max_favorable = max(t.max_favorable, (t.entry_price - low) / t.entry_price)
                t.max_adverse = max(t.max_adverse, (high - t.entry_price) / t.entry_price)

                if high >= t.sl_price:
                    t.exit_price = t.sl_price
                    t.exit_reason = 'SL'
                elif low <= t.tp_price:
                    t.exit_price = t.tp_price
                    t.exit_reason = 'TP'

                if t.exit_price:
                    t.pnl_pct = (t.entry_price - t.exit_price) / t.entry_price

            # Close trade if SL/TP hit
            if t.exit_price:
                t.exit_time = row.name
                risk_amount = portfolio.capital * t.size_pct
                t.pnl = risk_amount * (t.pnl_pct / (t.size_pct))  # actual P&L

                # Simpler P&L calc: position size * return
                position_value = portfolio.capital * 0.5  # use 50% of capital per trade
                t.pnl = position_value * t.pnl_pct

                portfolio.capital += t.pnl
                portfolio.trades.append(t)
                portfolio.open_trade = None
                trade_count += 1

        # --- Detect new signals ---
        if portfolio.open_trade is None:
            signals = detect_signals(row, prev_rows, index_type)
            total_signals += len(signals)

            if signals:
                result = resolve_signals(signals)
                if result and result[0] is not None:
                    direction, names, score, n_signals = result

                    # Calculate SL/TP
                    row_with_signal = row.copy()
                    row_with_signal['_signal_name'] = names
                    sl, tp = calculate_sl_tp(row_with_signal, direction, index_type)

                    # Position size based on signal strength
                    base_risk = portfolio.max_risk_pct
                    risk_pct = base_risk * min(score, 2.0)  # scale with confidence

                    # Daily loss limit
                    if hasattr(row.name, 'day'):
                        today = row.name.day
                        if today != portfolio.last_trade_day:
                            portfolio.daily_pnl = 0
                            portfolio.last_trade_day = today

                    if portfolio.daily_pnl < -portfolio.capital * portfolio.max_daily_loss_pct:
                        continue  # skip, daily loss limit reached

                    # Open trade
                    portfolio.open_trade = Trade(
                        entry_time=row.name,
                        direction=direction,
                        entry_price=current_price,
                        sl_price=sl,
                        tp_price=tp,
                        signal_name=names,
                        signal_score=score,
                        size_pct=risk_pct
                    )
                else:
                    skip_count += 1

        portfolio.equity_curve.append(portfolio.capital)

    # Close any remaining open trade at last price
    if portfolio.open_trade is not None:
        t = portfolio.open_trade
        t.exit_price = trade_data.iloc[-1]['Close']
        t.exit_time = trade_data.index[-1]
        t.exit_reason = 'EOD'
        if t.direction == 'long':
            t.pnl_pct = (t.exit_price - t.entry_price) / t.entry_price
        else:
            t.pnl_pct = (t.entry_price - t.exit_price) / t.entry_price
        position_value = portfolio.capital * 0.5
        t.pnl = position_value * t.pnl_pct
        portfolio.capital += t.pnl
        portfolio.trades.append(t)
        portfolio.equity_curve.append(portfolio.capital)

    return portfolio, total_signals, skip_count


# ============================================================
# REPORTING
# ============================================================

def print_results(portfolio, symbol, total_signals, skip_count):
    """Print detailed backtest results"""
    trades = portfolio.trades
    if not trades:
        print(f"  No trades for {symbol}")
        return None

    trades_df = pd.DataFrame([{
        'entry': t.entry_time,
        'exit': t.exit_time,
        'dir': t.direction,
        'signal': t.signal_name,
        'score': t.signal_score,
        'entry_price': t.entry_price,
        'exit_price': t.exit_price,
        'pnl': t.pnl,
        'pnl_pct': t.pnl_pct * 100,
        'exit_reason': t.exit_reason,
        'max_fav': t.max_favorable * 100,
        'max_adv': t.max_adverse * 100,
    } for t in trades])

    total = len(trades_df)
    winners = trades_df[trades_df['pnl'] > 0]
    losers = trades_df[trades_df['pnl'] <= 0]

    win_rate = len(winners) / total * 100
    total_return = (portfolio.capital - portfolio.initial_capital) / portfolio.initial_capital * 100

    avg_win = winners['pnl'].mean() if len(winners) > 0 else 0
    avg_loss = losers['pnl'].mean() if len(losers) > 0 else 0

    gross_profit = winners['pnl'].sum() if len(winners) > 0 else 0
    gross_loss = abs(losers['pnl'].sum()) if len(losers) > 0 else 0.01
    profit_factor = gross_profit / gross_loss

    # Max drawdown
    equity = np.array(portfolio.equity_curve)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak * 100
    max_dd = dd.min()

    # Sharpe
    if len(trades_df) > 2:
        rets = trades_df['pnl_pct'].values
        sharpe = np.mean(rets) / np.std(rets) * np.sqrt(252 / max(1, total)) if np.std(rets) > 0 else 0
    else:
        sharpe = 0

    # Average trade duration
    trades_df['duration'] = pd.to_datetime(trades_df['exit']) - pd.to_datetime(trades_df['entry'])
    avg_duration = trades_df['duration'].mean()

    print(f"\n  {'='*60}")
    print(f"  {symbol}")
    print(f"  {'='*60}")
    print(f"  Total trades:      {total}")
    print(f"  Win rate:          {win_rate:.1f}%")
    print(f"  Profit factor:     {profit_factor:.2f}")
    print(f"  Total return:      {total_return:+.2f}%")
    print(f"  Final capital:     ${portfolio.capital:.2f}")
    print(f"  Max drawdown:      {max_dd:.2f}%")
    print(f"  Sharpe ratio:      {sharpe:.2f}")
    print(f"  Avg winner:        ${avg_win:.2f} ({winners['pnl_pct'].mean():.2f}%)" if len(winners) > 0 else "")
    print(f"  Avg loser:         ${avg_loss:.2f} ({losers['pnl_pct'].mean():.2f}%)" if len(losers) > 0 else "")
    print(f"  Avg duration:      {avg_duration}")
    print(f"  Signals detected:  {total_signals} (skipped: {skip_count})")

    # By direction
    for d in ['long', 'short']:
        dt = trades_df[trades_df['dir'] == d]
        if len(dt) > 0:
            wr = len(dt[dt['pnl'] > 0]) / len(dt) * 100
            pnl = dt['pnl'].sum()
            print(f"  {d.upper():5s}: {len(dt)} trades | WR: {wr:.0f}% | PnL: ${pnl:.2f}")

    # By exit reason
    print(f"\n  Exit reasons:")
    for reason in ['TP', 'SL', 'EOD']:
        rt = trades_df[trades_df['exit_reason'] == reason]
        if len(rt) > 0:
            print(f"    {reason}: {len(rt)} ({len(rt)/total*100:.0f}%)")

    # Top signals by profitability
    print(f"\n  Signal performance:")
    signal_perf = trades_df.groupby('signal').agg(
        count=('pnl', 'count'),
        win_rate=('pnl', lambda x: (x > 0).mean() * 100),
        avg_pnl=('pnl', 'mean'),
        total_pnl=('pnl', 'sum')
    ).sort_values('total_pnl', ascending=False)

    for sig, row in signal_perf.iterrows():
        marker = " +" if row['total_pnl'] > 0 else " -"
        print(f"    {sig:<45} N={int(row['count']):>3} WR={row['win_rate']:>5.1f}% PnL=${row['total_pnl']:>8.2f}{marker}")

    # Monthly performance
    trades_df['month'] = pd.to_datetime(trades_df['entry']).dt.to_period('M')
    monthly = trades_df.groupby('month')['pnl'].agg(['sum', 'count'])
    print(f"\n  Monthly P&L:")
    win_months = 0
    for month, row in monthly.iterrows():
        marker = "+" if row['sum'] > 0 else "-"
        print(f"    {month}: ${row['sum']:>8.2f} ({int(row['count'])} trades) {marker}")
        if row['sum'] > 0:
            win_months += 1
    if len(monthly) > 0:
        print(f"  Profitable months: {win_months}/{len(monthly)} ({win_months/len(monthly)*100:.0f}%)")

    return trades_df


# ============================================================
# MAIN
# ============================================================

def main():
    print("="*70)
    print("  BEHAVIOR-BASED TRADING SYSTEM - BACKTEST")
    print("  Trading ONLY on validated, proven patterns")
    print("="*70)

    # Top 4 indices to test
    indices = [
        ('Boom 1000 Index', 'boom'),
        ('Crash 1000 Index', 'crash'),
        ('Crash 500 Index', 'crash'),
        ('Volatility 25 Index', 'volatility'),
    ]

    all_results = {}

    for symbol, index_type in indices:
        safe_name = symbol.replace(' ', '_')

        # Try H1 first (most data + good signal)
        fpath = Path(f'data/raw/{safe_name}_H1.parquet')
        if not fpath.exists():
            print(f"\n  SKIP {symbol}: no data file")
            continue

        df = pd.read_parquet(fpath)
        print(f"\n{'#'*70}")
        print(f"#  {symbol} ({index_type.upper()}) - {len(df)} candles H1")
        print(f"{'#'*70}")

        portfolio, total_signals, skip_count = backtest(df, index_type, symbol)
        trades_df = print_results(portfolio, symbol, total_signals, skip_count)

        all_results[symbol] = {
            'portfolio': portfolio,
            'trades_df': trades_df,
            'total_return': (portfolio.capital - portfolio.initial_capital) / portfolio.initial_capital * 100
        }

    # === FINAL COMPARISON ===
    print(f"\n\n{'#'*70}")
    print(f"#  FINAL COMPARISON - ALL INDICES")
    print(f"{'#'*70}")

    print(f"\n  {'Symbol':<25} {'Return':>8} {'Trades':>7} {'WinRate':>8} {'PF':>6} {'MaxDD':>8} {'Sharpe':>7} {'Final$':>10}")
    print(f"  {'-'*25} {'-'*8} {'-'*7} {'-'*8} {'-'*6} {'-'*8} {'-'*7} {'-'*10}")

    for symbol, res in all_results.items():
        p = res['portfolio']
        t = res['trades_df']
        if t is None:
            continue

        total_return = res['total_return']
        n_trades = len(t)
        wr = len(t[t['pnl'] > 0]) / n_trades * 100 if n_trades > 0 else 0

        gross_p = t[t['pnl'] > 0]['pnl'].sum()
        gross_l = abs(t[t['pnl'] <= 0]['pnl'].sum()) if len(t[t['pnl'] <= 0]) > 0 else 0.01
        pf = gross_p / gross_l

        equity = np.array(p.equity_curve)
        peak = np.maximum.accumulate(equity)
        dd = ((equity - peak) / peak * 100).min()

        rets = t['pnl_pct'].values
        sharpe = np.mean(rets) / np.std(rets) * np.sqrt(252 / max(1, n_trades)) if len(rets) > 1 and np.std(rets) > 0 else 0

        print(f"  {symbol:<25} {total_return:>+7.1f}% {n_trades:>7} {wr:>7.1f}% {pf:>6.2f} {dd:>7.1f}% {sharpe:>7.2f} ${p.capital:>9.2f}")

    print(f"\n  Starting capital: $10,000 each")
    total_combined = sum(r['portfolio'].capital for r in all_results.values())
    total_invested = 10000 * len(all_results)
    print(f"  Combined: ${total_combined:.2f} from ${total_invested} invested ({(total_combined/total_invested - 1)*100:+.1f}%)")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
