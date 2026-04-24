#!/usr/bin/env python3
"""
LIVE DEMO BOT - Crash 1000 Index
=================================
Connects to Deriv WebSocket API in real-time.
Uses v3 behavior-based signals (proven in backtest).
Trades on demo account with Multipliers contracts.

Usage:
  1. Set your DERIV_API_TOKEN in .env file
  2. python bot_demo.py
  3. Bot runs continuously, prints signals and trades

Requirements:
  - Deriv demo account with API token (trading + read permissions)
  - Token from: https://app.deriv.com/account/api-token
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIG
# ============================================================

CONFIG = {
    'symbol': 'CRASH1000',
    'symbol_display': 'Crash 1000 Index',
    'app_id': '1089',

    # Timeframes (in seconds)
    'entry_tf': 3600,      # H1 for entries
    'trend_tf': 14400,     # H4 for trend filter

    # Candle history needed
    'h1_history': 120,     # 120 H1 candles for indicators
    'h4_history': 60,      # 60 H4 candles for trend

    # Trading params
    'stake_amount': 1.0,   # USD per trade (start small on demo)
    'multiplier': 100,     # Multiplier value
    'sl_pct': 1.5,         # Stop loss %
    'tp_pct': 3.0,         # Take profit %

    # Risk
    'max_open_trades': 1,
    'cooldown_minutes': 60,  # Min time between trades
}


# ============================================================
# INDICATOR COMPUTATION
# ============================================================

def compute_indicators_live(candles):
    """Compute indicators from a list of candle dicts"""
    if len(candles) < 60:
        return None

    df = pd.DataFrame(candles)
    for c in ['open', 'high', 'low', 'close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')

    df['ret'] = df['close'].pct_change()
    df['body_abs'] = (df['close'] - df['open']).abs()
    df['range'] = df['high'] - df['low']
    df['body_ratio'] = df['body_abs'] / df['range'].replace(0, np.nan)
    df['is_doji'] = (df['body_ratio'] < 0.1).astype(int)

    # Volatility
    df['vol_5'] = df['ret'].rolling(5).std()
    df['vol_20'] = df['ret'].rolling(20).std()
    df['vol_ratio'] = df['vol_5'] / df['vol_20']
    df['atr'] = df['range'].rolling(14).mean()

    # EMAs
    for s in [5, 10, 20, 50]:
        df[f'ema_{s}'] = df['close'].ewm(span=s, adjust=False).mean()

    df['dist_ema20'] = (df['close'] - df['ema_20']) / df['ema_20'] * 100

    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))

    # Crash spikes
    ret_std = df['ret'].rolling(50, min_periods=30).std()
    ret_mean = df['ret'].rolling(50, min_periods=30).mean()
    df['is_crash_spike'] = (df['ret'] < ret_mean - 3 * ret_std).astype(int)

    df['since_crash'] = 0
    c = 999
    for i in range(len(df)):
        if df['is_crash_spike'].iloc[i] == 1:
            c = 0
        else:
            c += 1
        df.iloc[i, df.columns.get_loc('since_crash')] = c

    # Consecutive down
    df['consec_down'] = 0
    dc = 0
    for i in range(len(df)):
        if df['ret'].iloc[i] < 0:
            dc += 1
        else:
            dc = 0
        df.iloc[i, df.columns.get_loc('consec_down')] = dc

    # Trend
    df['trend'] = 0
    df.loc[df['ema_5'] > df['ema_20'], 'trend'] = 1
    df.loc[df['ema_5'] < df['ema_20'], 'trend'] = -1

    return df


def detect_signal(h1_df, h4_df):
    """
    v3 signal detection for live trading.
    Returns: (should_trade, signal_name, score, reason)
    """
    if h1_df is None or len(h1_df) < 60:
        return False, '', 0, 'Not enough H1 data'

    row = h1_df.iloc[-1]
    prev = h1_df.iloc[-2]

    # H4 trend
    h4_trend = 0
    h4_rsi = 50
    if h4_df is not None and len(h4_df) > 20:
        h4_last = h4_df.iloc[-1]
        h4_trend = h4_last.get('trend', 0)
        h4_rsi = h4_last.get('rsi', 50)

    rsi = row.get('rsi', 50)
    is_doji = row.get('is_doji', 0)
    vol_ratio = row.get('vol_ratio', 1.0)
    since_crash = row.get('since_crash', 999)
    consec_down = row.get('consec_down', 0)
    dist_ema20 = row.get('dist_ema20', 0)

    # === FILTERS ===
    if is_doji:
        return False, '', 0, 'FILTER: Doji candle'

    if vol_ratio < 0.5:
        return False, '', 0, 'FILTER: Vol squeeze'

    if h4_trend == -1 and h4_rsi < 40:
        return False, '', 0, 'FILTER: H4 bearish'

    # === SIGNALS (LONG only) ===
    signals = []
    score = 0

    if 1 <= since_crash <= 3:
        signals.append('post_crash_recovery')
        score += 1.0

    if 20 <= rsi < 35:
        signals.append('rsi_oversold')
        score += 0.6

    if consec_down >= 3 and rsi > 20:
        signals.append('consec_reversal')
        score += 0.4

    if -3.0 < dist_ema20 < -1.0:
        signals.append('overextended_moderate')
        score += 0.3

    ema5 = row.get('ema_5', 0)
    ema20 = row.get('ema_20', 0)
    pema5 = prev.get('ema_5', 0)
    pema20 = prev.get('ema_20', 0)
    if ema5 > ema20 and pema5 <= pema20:
        signals.append('bullish_cross')
        score += 0.5

    if h4_trend == 1 and len(signals) > 0:
        signals.append('h4_bullish')
        score += 0.3

    # Entry rules
    has_strong = 'post_crash_recovery' in signals
    n_core = len([s for s in signals if s != 'h4_bullish'])

    if has_strong or n_core >= 2:
        name = '+'.join(signals)
        return True, name, score, f'ENTRY: {name} (score={score:.1f})'

    if signals:
        return False, '', score, f'WEAK: {"+".join(signals)} (need confluence)'

    return False, '', 0, 'No signal'


# ============================================================
# DERIV API CONNECTION
# ============================================================

class DerivBot:
    """Live trading bot for Deriv demo account"""

    def __init__(self, token):
        self.token = token
        self.ws = None
        self.ws_url = f"wss://ws.derivws.com/websockets/v3?app_id={CONFIG['app_id']}"

        # Candle storage
        self.h1_candles = deque(maxlen=CONFIG['h1_history'])
        self.h4_candles = deque(maxlen=CONFIG['h4_history'])

        # State
        self.authorized = False
        self.balance = 0
        self.open_contracts = []
        self.last_trade_time = None
        self.trades_today = 0
        self.total_pnl = 0
        self.trade_log = []

        # Request tracking
        self.req_id = 0
        self.pending = {}

    def next_id(self):
        self.req_id += 1
        return self.req_id

    async def connect(self):
        """Connect and authorize"""
        import websockets
        self.ws = await websockets.connect(self.ws_url, ping_interval=30)
        log("Connected to Deriv API")

        # Authorize
        rid = self.next_id()
        await self.ws.send(json.dumps({"authorize": self.token, "req_id": rid}))
        resp = await self.ws.recv()
        data = json.loads(resp)

        if 'error' in data:
            log(f"AUTH FAILED: {data['error']['message']}")
            return False

        auth = data.get('authorize', {})
        self.balance = float(auth.get('balance', 0))
        account = auth.get('loginid', 'unknown')
        currency = auth.get('currency', 'USD')
        is_virtual = auth.get('is_virtual', 0)

        log(f"Authorized: {account} | Balance: {self.balance} {currency} | Demo: {bool(is_virtual)}")

        if not is_virtual:
            log("WARNING: This is NOT a demo account! Stopping for safety.")
            return False

        self.authorized = True
        return True

    async def load_history(self):
        """Load historical candles for H1 and H4"""
        log("Loading historical candles...")

        # H1
        h1_candles = await self._fetch_candles(CONFIG['entry_tf'], CONFIG['h1_history'])
        if h1_candles:
            self.h1_candles.extend(h1_candles)
            log(f"  H1: {len(self.h1_candles)} candles loaded")

        # H4
        h4_candles = await self._fetch_candles(CONFIG['trend_tf'], CONFIG['h4_history'])
        if h4_candles:
            self.h4_candles.extend(h4_candles)
            log(f"  H4: {len(self.h4_candles)} candles loaded")

    async def _fetch_candles(self, granularity, count):
        """Fetch historical candles"""
        rid = self.next_id()
        req = {
            "ticks_history": CONFIG['symbol'],
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "granularity": granularity,
            "start": 1,
            "style": "candles",
            "req_id": rid
        }
        await self.ws.send(json.dumps(req))
        resp = await self.ws.recv()
        data = json.loads(resp)

        if 'error' in data:
            log(f"  Error fetching candles: {data['error']['message']}")
            return []

        return data.get('candles', [])

    async def subscribe_candles(self):
        """Subscribe to live candle updates for H1"""
        rid = self.next_id()
        req = {
            "ticks_history": CONFIG['symbol'],
            "adjust_start_time": 1,
            "count": 1,
            "end": "latest",
            "granularity": CONFIG['entry_tf'],
            "start": 1,
            "style": "candles",
            "subscribe": 1,
            "req_id": rid
        }
        await self.ws.send(json.dumps(req))
        log("Subscribed to H1 candle stream")

    async def check_signal_and_trade(self):
        """Run signal detection and trade if conditions met"""

        # Compute indicators
        h1_df = compute_indicators_live(list(self.h1_candles))
        h4_df = compute_indicators_live(list(self.h4_candles))

        # Detect signal
        should_trade, signal_name, score, reason = detect_signal(h1_df, h4_df)

        now = datetime.utcnow().strftime('%H:%M:%S')

        if not should_trade:
            log(f"[{now}] {reason}")
            return

        # Check cooldown
        if self.last_trade_time:
            elapsed = (datetime.utcnow() - self.last_trade_time).total_seconds() / 60
            if elapsed < CONFIG['cooldown_minutes']:
                log(f"[{now}] SIGNAL: {signal_name} -- COOLDOWN ({elapsed:.0f}/{CONFIG['cooldown_minutes']} min)")
                return

        # Check max open trades
        if len(self.open_contracts) >= CONFIG['max_open_trades']:
            log(f"[{now}] SIGNAL: {signal_name} -- MAX TRADES OPEN")
            return

        log(f"[{now}] >>> SIGNAL DETECTED: {signal_name} (score={score:.1f}) <<<")

        # Execute trade
        await self.place_trade(signal_name, score)

    async def place_trade(self, signal_name, score):
        """Place a multiplier trade via Deriv API"""

        # Dynamic stake based on score
        stake = CONFIG['stake_amount']
        if score >= 1.5:
            stake *= 1.5

        log(f"  Placing BUY (Multiplier Up) | Stake: ${stake:.2f} | x{CONFIG['multiplier']}")

        rid = self.next_id()
        req = {
            "buy": 1,
            "subscribe": 1,
            "price": stake,
            "parameters": {
                "contract_type": "MULTUP",
                "symbol": CONFIG['symbol'],
                "amount": stake,
                "multiplier": CONFIG['multiplier'],
                "stop_loss": CONFIG['sl_pct'],
                "take_profit": CONFIG['tp_pct'],
                "basis": "stake",
                "currency": "USD",
            },
            "req_id": rid
        }

        await self.ws.send(json.dumps(req))
        self.pending[rid] = {'type': 'buy', 'signal': signal_name, 'score': score}

    def handle_buy_response(self, data, req_info):
        """Handle buy contract response"""
        if 'error' in data:
            log(f"  TRADE FAILED: {data['error']['message']}")
            return

        buy = data.get('buy', {})
        contract_id = buy.get('contract_id')
        buy_price = buy.get('buy_price', 0)

        log(f"  TRADE OPENED: Contract #{contract_id} | Cost: ${buy_price}")
        log(f"  Signal: {req_info.get('signal')} | Score: {req_info.get('score', 0):.1f}")

        self.open_contracts.append({
            'contract_id': contract_id,
            'signal': req_info.get('signal', ''),
            'buy_price': buy_price,
            'open_time': datetime.utcnow(),
        })
        self.last_trade_time = datetime.utcnow()
        self.trades_today += 1

    def handle_proposal_open_contract(self, data):
        """Handle contract update (profit/loss tracking)"""
        poc = data.get('proposal_open_contract', {})
        if not poc:
            return

        contract_id = poc.get('contract_id')
        profit = float(poc.get('profit', 0))
        status = poc.get('status', 'open')
        is_sold = poc.get('is_sold', 0)
        exit_spot = poc.get('exit_tick_display_value', '')

        if is_sold:
            log(f"  CONTRACT CLOSED: #{contract_id} | P&L: ${profit:+.2f} | Status: {status}")
            self.total_pnl += profit

            # Remove from open
            self.open_contracts = [c for c in self.open_contracts if c['contract_id'] != contract_id]

            # Log trade
            self.trade_log.append({
                'time': datetime.utcnow().isoformat(),
                'contract_id': contract_id,
                'profit': profit,
                'status': status,
            })

            log(f"  Total P&L: ${self.total_pnl:+.2f} | Open: {len(self.open_contracts)} | Today: {self.trades_today}")

    async def run(self):
        """Main bot loop"""
        log("="*60)
        log("  CRASH 1000 DEMO BOT - Starting")
        log("="*60)

        # Connect
        if not await self.connect():
            return

        # Load history
        await self.load_history()

        # Subscribe to candles
        await self.subscribe_candles()

        # Initial signal check
        await self.check_signal_and_trade()

        # Main loop - listen for candle updates
        log("\nBot running. Waiting for new H1 candles...")
        log("Press Ctrl+C to stop.\n")

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(self.ws.recv(), timeout=30)
                    data = json.loads(msg)

                    msg_type = data.get('msg_type', '')

                    # New candle (OHLC update)
                    if msg_type == 'ohlc':
                        ohlc = data.get('ohlc', {})
                        # Check if this is a completed candle
                        is_complete = ohlc.get('open_time') != ohlc.get('epoch')

                        # Update latest H1 candle
                        candle = {
                            'epoch': int(ohlc.get('open_time', 0)),
                            'open': ohlc.get('open', 0),
                            'high': ohlc.get('high', 0),
                            'low': ohlc.get('low', 0),
                            'close': ohlc.get('close', 0),
                        }

                        # If new candle started, the previous one is complete
                        if self.h1_candles and candle['epoch'] != self.h1_candles[-1].get('epoch', 0):
                            # New candle - previous is finalized
                            self.h1_candles.append(candle)
                            log(f"\n  New H1 candle: Close={candle['close']} | RSI check...")

                            # Refresh H4 periodically
                            if len(self.h1_candles) % 4 == 0:
                                h4_candles = await self._fetch_candles(CONFIG['trend_tf'], CONFIG['h4_history'])
                                if h4_candles:
                                    self.h4_candles.clear()
                                    self.h4_candles.extend(h4_candles)

                            # Check for signals
                            await self.check_signal_and_trade()
                        else:
                            # Update current candle in-place
                            if self.h1_candles:
                                self.h1_candles[-1] = candle

                    # Buy response
                    elif msg_type == 'buy':
                        rid = data.get('req_id')
                        req_info = self.pending.pop(rid, {})
                        self.handle_buy_response(data, req_info)

                    # Contract update
                    elif msg_type == 'proposal_open_contract':
                        self.handle_proposal_open_contract(data)

                except asyncio.TimeoutError:
                    # Heartbeat - keep alive
                    await self.ws.send(json.dumps({"ping": 1}))

        except KeyboardInterrupt:
            log("\n\nBot stopped by user")
        except Exception as e:
            log(f"\nBot error: {e}")
        finally:
            # Summary
            log("\n" + "="*60)
            log("  SESSION SUMMARY")
            log("="*60)
            log(f"  Trades: {len(self.trade_log)}")
            log(f"  Total P&L: ${self.total_pnl:+.2f}")
            if self.trade_log:
                wins = sum(1 for t in self.trade_log if t['profit'] > 0)
                log(f"  Win rate: {wins/len(self.trade_log)*100:.0f}%")
            log("="*60)

            if self.ws:
                await self.ws.close()


# ============================================================
# LOGGING
# ============================================================

def log(msg):
    """Print with timestamp"""
    ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{ts}] {msg}")

    # Also log to file
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)
    with open(log_dir / 'bot_demo.log', 'a') as f:
        f.write(f"[{ts}] {msg}\n")


# ============================================================
# MAIN
# ============================================================

def main():
    token = os.getenv('DERIV_API_TOKEN')

    if not token:
        print("="*60)
        print("  SETUP REQUIRED")
        print("="*60)
        print()
        print("  1. Go to: https://app.deriv.com/account/api-token")
        print("  2. Create a token with 'Trade' and 'Read' permissions")
        print("  3. Create a .env file with:")
        print()
        print("     DERIV_API_TOKEN=your_token_here")
        print()
        print("  4. Run again: python bot_demo.py")
        print()
        print("="*60)
        return

    bot = DerivBot(token)
    asyncio.run(bot.run())


if __name__ == "__main__":
    main()
