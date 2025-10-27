"""
Backtest Engine - Système de backtesting pour stratégies de trading
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
from loguru import logger


@dataclass
class Trade:
    """Représente une transaction"""
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    position_size: float = 0.0
    direction: str = 'long'  # 'long' or 'short'
    pnl: float = 0.0
    pnl_pct: float = 0.0
    status: str = 'open'  # 'open', 'closed', 'stopped'
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class BacktestEngine:
    """Moteur de backtesting"""

    def __init__(
        self,
        initial_capital: float = 10000,
        position_size: float = 0.02,
        max_positions: int = 1,
        commission: float = 0.0,
        slippage: float = 0.0001,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        trailing_stop: bool = False
    ):
        """
        Initialize backtest engine

        Args:
            initial_capital: Starting capital
            position_size: Position size as fraction of capital
            max_positions: Maximum concurrent positions
            commission: Commission per trade (as fraction)
            slippage: Slippage per trade (as fraction)
            stop_loss: Stop loss (as fraction, e.g., 0.02 = 2%)
            take_profit: Take profit (as fraction)
            trailing_stop: Use trailing stop loss
        """
        self.initial_capital = initial_capital
        self.position_size = position_size
        self.max_positions = max_positions
        self.commission = commission
        self.slippage = slippage
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.trailing_stop = trailing_stop

        # State
        self.capital = initial_capital
        self.trades: List[Trade] = []
        self.open_trades: List[Trade] = []
        self.equity_curve: List[float] = []
        self.timestamps: List[datetime] = []

        logger.info(f"Backtest engine initialized with ${initial_capital:.2f}")

    def can_open_position(self) -> bool:
        """Check if we can open a new position"""
        return len(self.open_trades) < self.max_positions

    def calculate_position_size(self, price: float) -> float:
        """
        Calculate position size in units

        Args:
            price: Current price

        Returns:
            Number of units to trade
        """
        # Amount to invest
        amount = self.capital * self.position_size

        # Number of units
        units = amount / price

        return units

    def open_position(
        self,
        timestamp: datetime,
        price: float,
        direction: str = 'long'
    ) -> bool:
        """
        Open a new position

        Args:
            timestamp: Entry timestamp
            price: Entry price
            direction: 'long' or 'short'

        Returns:
            True if position was opened
        """
        if not self.can_open_position():
            return False

        # Calculate position size
        units = self.calculate_position_size(price)

        if units <= 0:
            return False

        # Apply slippage
        if direction == 'long':
            entry_price = price * (1 + self.slippage)
        else:
            entry_price = price * (1 - self.slippage)

        # Calculate stop loss and take profit levels
        if self.stop_loss:
            if direction == 'long':
                stop_loss_price = entry_price * (1 - self.stop_loss)
            else:
                stop_loss_price = entry_price * (1 + self.stop_loss)
        else:
            stop_loss_price = None

        if self.take_profit:
            if direction == 'long':
                take_profit_price = entry_price * (1 + self.take_profit)
            else:
                take_profit_price = entry_price * (1 - self.take_profit)
        else:
            take_profit_price = None

        # Create trade
        trade = Trade(
            entry_time=timestamp,
            entry_price=entry_price,
            position_size=units,
            direction=direction,
            stop_loss=stop_loss_price,
            take_profit=take_profit_price
        )

        # Add commission
        commission_cost = entry_price * units * self.commission
        self.capital -= commission_cost

        # Add to open trades
        self.open_trades.append(trade)

        logger.debug(f"Opened {direction} position: {units:.4f} units @ ${entry_price:.2f}")

        return True

    def close_position(
        self,
        trade: Trade,
        timestamp: datetime,
        price: float,
        reason: str = 'signal'
    ) -> float:
        """
        Close an open position

        Args:
            trade: Trade to close
            timestamp: Exit timestamp
            price: Exit price
            reason: Reason for closing ('signal', 'stop_loss', 'take_profit')

        Returns:
            Profit/loss
        """
        # Apply slippage
        if trade.direction == 'long':
            exit_price = price * (1 - self.slippage)
        else:
            exit_price = price * (1 + self.slippage)

        # Calculate PnL
        if trade.direction == 'long':
            pnl = (exit_price - trade.entry_price) * trade.position_size
            pnl_pct = (exit_price / trade.entry_price - 1) * 100
        else:
            pnl = (trade.entry_price - exit_price) * trade.position_size
            pnl_pct = (trade.entry_price / exit_price - 1) * 100

        # Subtract commission
        commission_cost = exit_price * trade.position_size * self.commission
        pnl -= commission_cost

        # Update capital
        self.capital += pnl

        # Update trade
        trade.exit_time = timestamp
        trade.exit_price = exit_price
        trade.pnl = pnl
        trade.pnl_pct = pnl_pct
        trade.status = reason

        # Remove from open trades
        self.open_trades.remove(trade)

        # Add to closed trades
        self.trades.append(trade)

        logger.debug(f"Closed position: PnL=${pnl:.2f} ({pnl_pct:.2f}%) - Reason: {reason}")

        return pnl

    def update_trailing_stop(self, trade: Trade, current_price: float):
        """Update trailing stop loss"""
        if not self.trailing_stop or not trade.stop_loss:
            return

        if trade.direction == 'long':
            # Update stop loss if price moved up
            new_stop = current_price * (1 - self.stop_loss)
            if new_stop > trade.stop_loss:
                trade.stop_loss = new_stop
        else:
            # Update stop loss if price moved down
            new_stop = current_price * (1 + self.stop_loss)
            if new_stop < trade.stop_loss:
                trade.stop_loss = new_stop

    def check_stops(self, timestamp: datetime, current_price: float):
        """Check stop loss and take profit for open positions"""
        for trade in self.open_trades.copy():
            # Update trailing stop
            self.update_trailing_stop(trade, current_price)

            # Check stop loss
            if trade.stop_loss:
                if trade.direction == 'long' and current_price <= trade.stop_loss:
                    self.close_position(trade, timestamp, current_price, 'stop_loss')
                    continue
                elif trade.direction == 'short' and current_price >= trade.stop_loss:
                    self.close_position(trade, timestamp, current_price, 'stop_loss')
                    continue

            # Check take profit
            if trade.take_profit:
                if trade.direction == 'long' and current_price >= trade.take_profit:
                    self.close_position(trade, timestamp, current_price, 'take_profit')
                    continue
                elif trade.direction == 'short' and current_price <= trade.take_profit:
                    self.close_position(trade, timestamp, current_price, 'take_profit')
                    continue

    def calculate_equity(self, current_price: float) -> float:
        """
        Calculate current equity (capital + unrealized PnL)

        Args:
            current_price: Current market price

        Returns:
            Total equity
        """
        equity = self.capital

        # Add unrealized PnL from open positions
        for trade in self.open_trades:
            if trade.direction == 'long':
                unrealized_pnl = (current_price - trade.entry_price) * trade.position_size
            else:
                unrealized_pnl = (trade.entry_price - current_price) * trade.position_size

            equity += unrealized_pnl

        return equity

    def run(
        self,
        data: pd.DataFrame,
        signal_func: Callable[[pd.DataFrame, int], int],
        price_column: str = 'Close'
    ):
        """
        Run backtest

        Args:
            data: DataFrame with OHLCV data
            signal_func: Function that returns signal (1=long, -1=short, 0=close)
            price_column: Column to use for prices
        """
        logger.info(f"Running backtest on {len(data)} bars...")

        for i in range(len(data)):
            timestamp = data.index[i]
            price = data[price_column].iloc[i]

            # Check stops first
            self.check_stops(timestamp, price)

            # Get signal
            signal = signal_func(data, i)

            # Execute signal
            if signal == 1:  # Long signal
                if self.can_open_position():
                    self.open_position(timestamp, price, 'long')

            elif signal == -1:  # Short signal
                if self.can_open_position():
                    self.open_position(timestamp, price, 'short')

            elif signal == 0:  # Close signal
                for trade in self.open_trades.copy():
                    self.close_position(trade, timestamp, price, 'signal')

            # Calculate and store equity
            equity = self.calculate_equity(price)
            self.equity_curve.append(equity)
            self.timestamps.append(timestamp)

        # Close any remaining open positions
        if len(self.open_trades) > 0:
            last_price = data[price_column].iloc[-1]
            last_timestamp = data.index[-1]
            for trade in self.open_trades.copy():
                self.close_position(trade, last_timestamp, last_price, 'end_of_data')

        logger.info("Backtest complete!")

    def get_results(self) -> Dict:
        """
        Calculate and return backtest results

        Returns:
            Dictionary with performance metrics
        """
        if not self.trades:
            logger.warning("No trades executed")
            return {}

        # Basic statistics
        num_trades = len(self.trades)
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl < 0]

        win_rate = len(winning_trades) / num_trades if num_trades > 0 else 0

        # PnL
        total_pnl = sum(t.pnl for t in self.trades)
        total_return = (self.capital / self.initial_capital - 1) * 100

        avg_win = np.mean([t.pnl for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.pnl for t in losing_trades]) if losing_trades else 0

        # Profit factor
        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.inf

        # Drawdown
        equity_curve = np.array(self.equity_curve)
        peak = np.maximum.accumulate(equity_curve)
        drawdown = (equity_curve - peak) / peak
        max_drawdown = np.min(drawdown) * 100

        # Sharpe ratio (simplified)
        returns = np.diff(equity_curve) / equity_curve[:-1]
        sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0

        # Sortino ratio
        downside_returns = returns[returns < 0]
        downside_std = np.std(downside_returns) if len(downside_returns) > 0 else 1
        sortino_ratio = np.mean(returns) / downside_std * np.sqrt(252)

        # Average trade duration
        trade_durations = []
        for trade in self.trades:
            if trade.exit_time and trade.entry_time:
                duration = (trade.exit_time - trade.entry_time).total_seconds() / 3600  # hours
                trade_durations.append(duration)

        avg_duration = np.mean(trade_durations) if trade_durations else 0

        results = {
            'total_trades': num_trades,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate * 100,
            'total_pnl': total_pnl,
            'total_return_pct': total_return,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_drawdown_pct': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'sortino_ratio': sortino_ratio,
            'avg_trade_duration_hours': avg_duration,
            'initial_capital': self.initial_capital,
            'final_capital': self.capital
        }

        return results

    def get_trades_df(self) -> pd.DataFrame:
        """Get trades as DataFrame"""
        if not self.trades:
            return pd.DataFrame()

        trades_data = []
        for trade in self.trades:
            trades_data.append({
                'entry_time': trade.entry_time,
                'entry_price': trade.entry_price,
                'exit_time': trade.exit_time,
                'exit_price': trade.exit_price,
                'direction': trade.direction,
                'position_size': trade.position_size,
                'pnl': trade.pnl,
                'pnl_pct': trade.pnl_pct,
                'status': trade.status
            })

        return pd.DataFrame(trades_data)

    def get_equity_curve_df(self) -> pd.DataFrame:
        """Get equity curve as DataFrame"""
        return pd.DataFrame({
            'timestamp': self.timestamps,
            'equity': self.equity_curve
        })

    def print_summary(self):
        """Print backtest summary"""
        results = self.get_results()

        if not results:
            print("No trades executed")
            return

        print("\n" + "=" * 60)
        print("BACKTEST RESULTS SUMMARY")
        print("=" * 60)
        print(f"\nInitial Capital:        ${results['initial_capital']:,.2f}")
        print(f"Final Capital:          ${results['final_capital']:,.2f}")
        print(f"Total PnL:              ${results['total_pnl']:,.2f}")
        print(f"Total Return:           {results['total_return_pct']:.2f}%")
        print(f"\nTotal Trades:           {results['total_trades']}")
        print(f"Winning Trades:         {results['winning_trades']}")
        print(f"Losing Trades:          {results['losing_trades']}")
        print(f"Win Rate:               {results['win_rate']:.2f}%")
        print(f"\nAverage Win:            ${results['avg_win']:.2f}")
        print(f"Average Loss:           ${results['avg_loss']:.2f}")
        print(f"Profit Factor:          {results['profit_factor']:.2f}")
        print(f"\nMax Drawdown:           {results['max_drawdown_pct']:.2f}%")
        print(f"Sharpe Ratio:           {results['sharpe_ratio']:.2f}")
        print(f"Sortino Ratio:          {results['sortino_ratio']:.2f}")
        print(f"\nAvg Trade Duration:     {results['avg_trade_duration_hours']:.1f} hours")
        print("=" * 60 + "\n")


def example_strategy(data: pd.DataFrame, index: int) -> int:
    """
    Example trading strategy
    Returns: 1 (long), -1 (short), 0 (close/do nothing)
    """
    if index < 20:
        return 0

    # Simple moving average crossover
    sma_fast = data['Close'].iloc[index-10:index].mean()
    sma_slow = data['Close'].iloc[index-20:index].mean()

    if sma_fast > sma_slow:
        return 1  # Long signal
    elif sma_fast < sma_slow:
        return -1  # Short signal
    else:
        return 0


def main():
    """Example usage"""
    # Load data
    data = pd.read_parquet("data/raw/Volatility_10_Index_M1.parquet")

    # Create backtest engine
    engine = BacktestEngine(
        initial_capital=10000,
        position_size=0.02,
        stop_loss=0.02,
        take_profit=0.04
    )

    # Run backtest
    engine.run(data, example_strategy)

    # Print results
    engine.print_summary()

    # Get trades
    trades_df = engine.get_trades_df()
    print("\nFirst 10 trades:")
    print(trades_df.head(10))


if __name__ == "__main__":
    main()
