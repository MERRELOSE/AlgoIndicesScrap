#!/usr/bin/env python3
"""
Baseline Trend-Following Model for Crash 500 Index
Based on statistical analysis findings:
  - Hurst > 0.5 on all timeframes (trending behavior)
  - Volatility clustering on H4 (predictable vol)
  - Pre-crash signal on H1 (slight bearish drift before spikes)

Strategy:
  1. Trend detection via multiple simple indicators
  2. XGBoost classifier for direction prediction
  3. Volatility-based position sizing
  4. Rigorous walk-forward backtesting
"""

import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from xgboost import XGBClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.preprocessing import StandardScaler
import warnings
warnings.filterwarnings('ignore')


# ============================================================
# FEATURE ENGINEERING - Based on what the stats told us
# ============================================================

def build_trend_features(df):
    """
    Build features focused on TREND detection (Hurst > 0.5)
    No bloat - only features justified by our statistical analysis
    """
    df = df.copy()

    # --- Returns at multiple horizons ---
    for n in [1, 2, 3, 4, 5, 10, 20]:
        df[f'ret_{n}'] = df['Close'].pct_change(n)

    # --- Trend indicators ---
    # EMA crossovers (trend detection)
    for span in [5, 10, 20, 50]:
        df[f'ema_{span}'] = df['Close'].ewm(span=span, adjust=False).mean()

    # Price relative to EMAs (above = uptrend, below = downtrend)
    df['price_vs_ema5'] = (df['Close'] - df['ema_5']) / df['ema_5']
    df['price_vs_ema10'] = (df['Close'] - df['ema_10']) / df['ema_10']
    df['price_vs_ema20'] = (df['Close'] - df['ema_20']) / df['ema_20']
    df['price_vs_ema50'] = (df['Close'] - df['ema_50']) / df['ema_50']

    # EMA slopes (trend strength)
    df['ema5_slope'] = df['ema_5'].pct_change(3)
    df['ema10_slope'] = df['ema_10'].pct_change(5)
    df['ema20_slope'] = df['ema_20'].pct_change(10)

    # EMA crossover signals
    df['ema5_above_ema20'] = (df['ema_5'] > df['ema_20']).astype(int)
    df['ema10_above_ema50'] = (df['ema_10'] > df['ema_50']).astype(int)

    # --- Volatility features (clustering detected on H4) ---
    df['atr_5'] = (df['High'] - df['Low']).rolling(5).mean()
    df['atr_20'] = (df['High'] - df['Low']).rolling(20).mean()
    df['vol_ratio'] = df['atr_5'] / df['atr_20']  # >1 = expanding vol, <1 = contracting

    # Rolling std of returns
    df['volatility_5'] = df['ret_1'].rolling(5).std()
    df['volatility_20'] = df['ret_1'].rolling(20).std()
    df['vol_expansion'] = df['volatility_5'] / df['volatility_20']

    # --- Momentum ---
    # RSI
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi_14'] = 100 - (100 / (1 + rs))

    # Rate of change
    df['roc_5'] = df['Close'].pct_change(5)
    df['roc_10'] = df['Close'].pct_change(10)
    df['roc_20'] = df['Close'].pct_change(20)

    # --- Mean reversion signals (to avoid, since Hurst > 0.5) ---
    # Bollinger Band position
    bb_mid = df['Close'].rolling(20).mean()
    bb_std = df['Close'].rolling(20).std()
    df['bb_position'] = (df['Close'] - bb_mid) / (2 * bb_std)

    # --- Candle patterns ---
    df['body_size'] = abs(df['Close'] - df['Open']) / (df['High'] - df['Low']).replace(0, np.nan)
    df['upper_shadow'] = (df['High'] - df[['Open', 'Close']].max(axis=1)) / (df['High'] - df['Low']).replace(0, np.nan)
    df['lower_shadow'] = (df[['Open', 'Close']].min(axis=1) - df['Low']) / (df['High'] - df['Low']).replace(0, np.nan)
    df['is_bullish'] = (df['Close'] > df['Open']).astype(int)

    # Consecutive bullish/bearish candles
    df['consec_bull'] = df['is_bullish'].rolling(5).sum()
    df['consec_bear'] = 5 - df['consec_bull']

    # --- Higher highs / Lower lows (trend structure) ---
    df['higher_high'] = (df['High'] > df['High'].shift(1)).astype(int)
    df['lower_low'] = (df['Low'] < df['Low'].shift(1)).astype(int)
    df['hh_count_5'] = df['higher_high'].rolling(5).sum()
    df['ll_count_5'] = df['lower_low'].rolling(5).sum()

    # --- Lag features (autocorrelation) ---
    for lag in [1, 2, 3, 5]:
        df[f'ret_lag_{lag}'] = df['ret_1'].shift(lag)
        df[f'vol_lag_{lag}'] = df['volatility_5'].shift(lag)

    # --- Target: next candle direction ---
    df['target'] = (df['Close'].shift(-1) > df['Close']).astype(int)

    return df


# ============================================================
# WALK-FORWARD BACKTESTING
# ============================================================

def walk_forward_test(df, feature_cols, models, train_size=500, test_size=50, step=50):
    """
    Walk-forward testing - the ONLY valid way to test time series models.
    Train on past, predict future, slide window forward.
    """
    results = {name: [] for name in models}
    all_predictions = {name: [] for name in models}

    n = len(df)
    start = train_size

    scaler = StandardScaler()

    while start + test_size <= n:
        # Split
        train_df = df.iloc[start - train_size:start]
        test_df = df.iloc[start:start + test_size]

        X_train = train_df[feature_cols].values
        y_train = train_df['target'].values
        X_test = test_df[feature_cols].values
        y_test = test_df['target'].values

        # Scale
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        # Train and predict each model
        for name, model_cls in models.items():
            model = model_cls()
            try:
                model.fit(X_train_scaled, y_train)
                preds = model.predict(X_test_scaled)
                acc = accuracy_score(y_test, preds)
                results[name].append(acc)

                for i, (pred, actual, idx) in enumerate(zip(preds, y_test, test_df.index)):
                    all_predictions[name].append({
                        'datetime': idx,
                        'predicted': pred,
                        'actual': actual,
                        'correct': pred == actual
                    })
            except Exception as e:
                pass

        start += step

    return results, all_predictions


# ============================================================
# TRADING SIMULATION
# ============================================================

def simulate_trading(predictions_df, ohlc_df, initial_capital=10000, risk_pct=0.02,
                     sl_pct=0.015, tp_pct=0.03):
    """
    Simulate actual trading based on model predictions.
    - Enter on prediction, exit on SL/TP or next signal
    - Track every trade, equity curve, drawdown
    """
    capital = initial_capital
    equity_curve = [capital]
    trades = []
    position = None  # None, 'long', 'short'
    entry_price = 0
    entry_time = None

    for i in range(len(predictions_df)):
        row = predictions_df.iloc[i]
        dt = row['datetime']

        # Get current price from OHLC
        if dt not in ohlc_df.index:
            continue
        current_price = ohlc_df.loc[dt, 'Close']
        high = ohlc_df.loc[dt, 'High']
        low = ohlc_df.loc[dt, 'Low']

        # Check SL/TP if in position
        if position is not None:
            sl_hit = False
            tp_hit = False

            if position == 'long':
                sl_hit = low <= entry_price * (1 - sl_pct)
                tp_hit = high >= entry_price * (1 + tp_pct)
            elif position == 'short':
                sl_hit = high >= entry_price * (1 + sl_pct)
                tp_hit = low <= entry_price * (1 - tp_pct)

            if sl_hit or tp_hit:
                # Close position
                if position == 'long':
                    if tp_hit:
                        exit_price = entry_price * (1 + tp_pct)
                    else:
                        exit_price = entry_price * (1 - sl_pct)
                    pnl_pct = (exit_price - entry_price) / entry_price
                else:
                    if tp_hit:
                        exit_price = entry_price * (1 - tp_pct)
                    else:
                        exit_price = entry_price * (1 + sl_pct)
                    pnl_pct = (entry_price - exit_price) / entry_price

                trade_size = capital * risk_pct / sl_pct
                pnl = trade_size * pnl_pct
                capital += pnl

                trades.append({
                    'entry_time': entry_time,
                    'exit_time': dt,
                    'direction': position,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct * 100,
                    'result': 'TP' if tp_hit else 'SL',
                    'capital_after': capital
                })

                position = None

        # New signal
        if position is None:
            pred = row['predicted']
            # For Crash 500: mainly short-biased (price tends down with crashes)
            # pred=1 means next candle UP, pred=0 means DOWN
            if pred == 1:
                position = 'long'
            else:
                position = 'short'

            entry_price = current_price
            entry_time = dt

        equity_curve.append(capital)

    return trades, equity_curve


def print_trading_results(trades, equity_curve, initial_capital=10000):
    """Print comprehensive trading results"""
    if not trades:
        print("  No trades executed")
        return

    trades_df = pd.DataFrame(trades)

    total_trades = len(trades_df)
    winners = trades_df[trades_df['pnl'] > 0]
    losers = trades_df[trades_df['pnl'] <= 0]

    win_rate = len(winners) / total_trades * 100
    total_pnl = trades_df['pnl'].sum()
    total_return = (equity_curve[-1] - initial_capital) / initial_capital * 100

    avg_win = winners['pnl'].mean() if len(winners) > 0 else 0
    avg_loss = losers['pnl'].mean() if len(losers) > 0 else 0
    profit_factor = abs(winners['pnl'].sum() / losers['pnl'].sum()) if len(losers) > 0 and losers['pnl'].sum() != 0 else float('inf')

    # Max drawdown
    equity = np.array(equity_curve)
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak * 100
    max_dd = drawdown.min()

    # Sharpe (approximate)
    if len(trades_df) > 1:
        returns = trades_df['pnl_pct'].values
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252 / max(1, total_trades)) if np.std(returns) > 0 else 0
    else:
        sharpe = 0

    print(f"\n  === TRADING RESULTS ===")
    print(f"  Total trades:    {total_trades}")
    print(f"  Win rate:        {win_rate:.1f}%")
    print(f"  Total P&L:       ${total_pnl:.2f}")
    print(f"  Total return:    {total_return:.2f}%")
    print(f"  Avg winner:      ${avg_win:.2f}")
    print(f"  Avg loser:       ${avg_loss:.2f}")
    print(f"  Profit factor:   {profit_factor:.2f}")
    print(f"  Max drawdown:    {max_dd:.2f}%")
    print(f"  Sharpe ratio:    {sharpe:.2f}")
    print(f"  Final capital:   ${equity_curve[-1]:.2f}")

    # Win/loss by direction
    for direction in ['long', 'short']:
        dir_trades = trades_df[trades_df['direction'] == direction]
        if len(dir_trades) > 0:
            dir_wr = len(dir_trades[dir_trades['pnl'] > 0]) / len(dir_trades) * 100
            print(f"  {direction.upper():5s} trades:  {len(dir_trades)} | WR: {dir_wr:.1f}%")

    return trades_df


# ============================================================
# MAIN
# ============================================================

def main():
    print("="*70)
    print("  BASELINE TREND-FOLLOWING MODEL - Crash 500 Index")
    print("="*70)

    # Load data - focus on H4 (strongest Hurst + vol clustering)
    timeframes = ['H4', 'H1', 'M15']

    for tf in timeframes:
        fpath = Path(f'data/raw/Crash_500_Index_{tf}.parquet')
        if not fpath.exists():
            print(f"\n  SKIP {tf}: no data file")
            continue

        df_raw = pd.read_parquet(fpath)
        print(f"\n{'='*70}")
        print(f"  TIMEFRAME: {tf} | {len(df_raw)} candles | {(df_raw.index[-1] - df_raw.index[0]).days} days")
        print(f"{'='*70}")

        # Build features
        df = build_trend_features(df_raw)

        # Drop NaN rows from feature calculation
        df = df.dropna()
        print(f"  After features: {len(df)} samples")

        # Feature columns (everything except target and raw OHLC/EMAs)
        exclude = ['Open', 'High', 'Low', 'Close', 'target',
                    'ema_5', 'ema_10', 'ema_20', 'ema_50']
        feature_cols = [c for c in df.columns if c not in exclude]
        print(f"  Features: {len(feature_cols)}")

        # Check for inf/nan in features
        df[feature_cols] = df[feature_cols].replace([np.inf, -np.inf], np.nan)
        df = df.dropna(subset=feature_cols + ['target'])
        print(f"  After cleaning: {len(df)} samples")

        # --- Models to test ---
        models = {
            'LogisticRegression': lambda: LogisticRegression(max_iter=1000, C=0.1),
            'RandomForest': lambda: RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42),
            'GradientBoosting': lambda: GradientBoostingClassifier(n_estimators=100, max_depth=3, learning_rate=0.1, random_state=42),
            'XGBoost': lambda: XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1, use_label_encoder=False, eval_metric='logloss', verbosity=0, random_state=42),
        }

        # --- Baseline: always predict majority class ---
        target_mean = df['target'].mean()
        print(f"\n  Baseline (always predict {'UP' if target_mean > 0.5 else 'DOWN'}): {max(target_mean, 1-target_mean)*100:.1f}%")

        # --- Walk-forward test ---
        if tf == 'H4':
            train_size, test_size, step = 400, 30, 30
        elif tf == 'H1':
            train_size, test_size, step = 1000, 100, 100
        else:
            train_size, test_size, step = 2000, 200, 200

        print(f"\n  Walk-forward: train={train_size}, test={test_size}, step={step}")
        print(f"  Estimated windows: ~{(len(df) - train_size) // step}")

        results, all_preds = walk_forward_test(df, feature_cols, models, train_size, test_size, step)

        # --- Results ---
        print(f"\n  --- DIRECTIONAL ACCURACY (walk-forward) ---")
        best_model = None
        best_acc = 0

        for name, accs in results.items():
            if accs:
                mean_acc = np.mean(accs) * 100
                std_acc = np.std(accs) * 100
                n_windows = len(accs)
                marker = " <-- BEST" if mean_acc > best_acc else ""
                if mean_acc > best_acc:
                    best_acc = mean_acc
                    best_model = name
                print(f"  {name:25s}: {mean_acc:.2f}% +/- {std_acc:.2f}% ({n_windows} windows){marker}")

        # --- Feature importance (best model) ---
        if best_model and best_model in ['RandomForest', 'GradientBoosting', 'XGBoost']:
            print(f"\n  --- TOP 15 FEATURES ({best_model}) ---")
            # Train on all data to get feature importance
            scaler = StandardScaler()
            X_all = scaler.fit_transform(df[feature_cols].values)
            y_all = df['target'].values

            if best_model == 'XGBoost':
                final_model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1,
                                           use_label_encoder=False, eval_metric='logloss',
                                           verbosity=0, random_state=42)
            elif best_model == 'GradientBoosting':
                final_model = GradientBoostingClassifier(n_estimators=100, max_depth=3,
                                                        learning_rate=0.1, random_state=42)
            else:
                final_model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)

            final_model.fit(X_all, y_all)
            importances = final_model.feature_importances_
            feat_imp = sorted(zip(feature_cols, importances), key=lambda x: x[1], reverse=True)

            for fname, imp in feat_imp[:15]:
                bar = "#" * int(imp * 200)
                print(f"    {fname:25s}: {imp:.4f} {bar}")

        # --- Trading Simulation with best model ---
        if best_model and all_preds.get(best_model):
            print(f"\n  --- TRADING SIMULATION ({best_model}) ---")
            pred_df = pd.DataFrame(all_preds[best_model])

            # Merge with OHLC
            trades, equity = simulate_trading(
                pred_df, df_raw,
                initial_capital=10000,
                risk_pct=0.02,
                sl_pct=0.015,
                tp_pct=0.03
            )

            trades_df = print_trading_results(trades, equity)

            # Also test with tighter SL for Crash index
            print(f"\n  --- TRADING SIM (tight SL=1%, TP=2%) ---")
            trades2, equity2 = simulate_trading(
                pred_df, df_raw,
                initial_capital=10000,
                risk_pct=0.02,
                sl_pct=0.01,
                tp_pct=0.02
            )
            print_trading_results(trades2, equity2)

    # --- Summary ---
    print(f"\n\n{'='*70}")
    print(f"  CONCLUSIONS")
    print(f"{'='*70}")
    print(f"""
  What we tested:
  - 4 ML models (LogReg, RF, GBM, XGBoost)
  - Walk-forward validation (no lookahead bias)
  - 3 timeframes (M15, H1, H4)
  - Features based on statistical findings (Hurst, vol clustering)

  Key metric: Directional accuracy > 50% = exploitable edge
  Secondary: Trading simulation with risk management

  Next steps based on results:
  - If accuracy > 53%: optimize and move to live testing
  - If accuracy 50-53%: try feature selection + hyperparameter tuning
  - If accuracy < 50%: revisit strategy, try different indices
""")


if __name__ == "__main__":
    main()
