"""
MT5 Data Extractor - Extraction de données depuis MetaTrader 5
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple
from loguru import logger
import yaml
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class MT5Extractor:
    """Classe pour extraire les données depuis MetaTrader 5"""

    TIMEFRAME_MAP = {
        'M1': mt5.TIMEFRAME_M1,
        'M5': mt5.TIMEFRAME_M5,
        'M15': mt5.TIMEFRAME_M15,
        'M30': mt5.TIMEFRAME_M30,
        'H1': mt5.TIMEFRAME_H1,
        'H4': mt5.TIMEFRAME_H4,
        'D1': mt5.TIMEFRAME_D1,
        'W1': mt5.TIMEFRAME_W1,
        'MN1': mt5.TIMEFRAME_MN1,
    }

    def __init__(self, config_path: str = "config/config.yaml"):
        """
        Initialize MT5 Extractor

        Args:
            config_path: Path to configuration file
        """
        self.config = self._load_config(config_path)
        self.connected = False

    def _load_config(self, config_path: str) -> dict:
        """Load configuration from YAML file and override with .env variables"""
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        # Override MT5 config with environment variables if present
        if 'mt5' not in config:
            config['mt5'] = {}

        # Priority: .env > config.yaml
        if os.getenv('MT5_LOGIN'):
            config['mt5']['login'] = os.getenv('MT5_LOGIN')
        if os.getenv('MT5_PASSWORD'):
            config['mt5']['password'] = os.getenv('MT5_PASSWORD')
        if os.getenv('MT5_SERVER'):
            config['mt5']['server'] = os.getenv('MT5_SERVER')
        if os.getenv('MT5_PATH'):
            config['mt5']['path'] = os.getenv('MT5_PATH')

        return config

    def connect(self) -> bool:
        """
        Connect to MT5 terminal

        Returns:
            bool: True if connection successful
        """
        try:
            # Get login and convert to integer
            login = self.config['mt5']['login']
            if isinstance(login, str):
                login = int(login)

            server = self.config['mt5']['server']

            logger.info(f"Attempting to connect to MT5...")
            logger.debug(f"Login: {login}, Server: {server}")

            # Initialize MT5
            if not mt5.initialize(
                path=self.config['mt5'].get('path'),
                login=login,
                password=self.config['mt5']['password'],
                server=server,
                timeout=self.config['mt5'].get('timeout', 60000)
            ):
                error_code, error_msg = mt5.last_error()
                logger.error(f"MT5 initialization failed: ({error_code}, '{error_msg}')")
                logger.error(f"Verify that:")
                logger.error(f"  1. MT5 is installed and running")
                logger.error(f"  2. Login: {login} is correct")
                logger.error(f"  3. Server: {server} is correct")
                logger.error(f"  4. Password in .env is correct")
                return False

            # Check connection
            account_info = mt5.account_info()
            if account_info is None:
                logger.error("Failed to get account info")
                return False

            self.connected = True
            logger.info(f"Connected to MT5: Account {account_info.login}, Server {account_info.server}")
            logger.info(f"Balance: {account_info.balance}, Equity: {account_info.equity}")

            return True

        except Exception as e:
            logger.error(f"Connection error: {e}")
            return False

    def disconnect(self):
        """Disconnect from MT5"""
        if self.connected:
            mt5.shutdown()
            self.connected = False
            logger.info("Disconnected from MT5")

    def get_symbols(self, filter_text: str = "") -> List[str]:
        """
        Get list of available symbols

        Args:
            filter_text: Filter symbols by text

        Returns:
            List of symbol names
        """
        if not self.connected:
            logger.error("Not connected to MT5")
            return []

        symbols = mt5.symbols_get(filter_text)
        if symbols is None:
            logger.error("Failed to get symbols")
            return []

        return [s.name for s in symbols]

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """
        Get detailed information about a symbol

        Args:
            symbol: Symbol name

        Returns:
            Dictionary with symbol information
        """
        if not self.connected:
            logger.error("Not connected to MT5")
            return None

        info = mt5.symbol_info(symbol)
        if info is None:
            logger.error(f"Failed to get info for {symbol}")
            return None

        return {
            'name': info.name,
            'description': info.description,
            'point': info.point,
            'digits': info.digits,
            'spread': info.spread,
            'tick_size': info.trade_tick_size,
            'tick_value': info.trade_tick_value,
            'volume_min': info.volume_min,
            'volume_max': info.volume_max,
            'currency_base': info.currency_base,
            'currency_profit': info.currency_profit,
        }

    def extract_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        bars: Optional[int] = None
    ) -> Optional[pd.DataFrame]:
        """
        Extract OHLCV data

        Args:
            symbol: Symbol name
            timeframe: Timeframe (M1, M5, H1, etc.)
            start_date: Start date
            end_date: End date
            bars: Number of bars (alternative to dates)

        Returns:
            DataFrame with OHLCV data
        """
        if not self.connected:
            logger.error("Not connected to MT5")
            return None

        if timeframe not in self.TIMEFRAME_MAP:
            logger.error(f"Invalid timeframe: {timeframe}")
            return None

        mt5_timeframe = self.TIMEFRAME_MAP[timeframe]

        try:
            # Get rates
            if bars:
                rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, bars)
            else:
                if start_date is None:
                    start_date = datetime.now() - timedelta(days=365)
                if end_date is None:
                    end_date = datetime.now()

                rates = mt5.copy_rates_range(symbol, mt5_timeframe, start_date, end_date)

            if rates is None or len(rates) == 0:
                logger.error(f"Failed to get rates for {symbol}")
                return None

            # Convert to DataFrame
            df = pd.DataFrame(rates)

            # Convert time to datetime
            df['time'] = pd.to_datetime(df['time'], unit='s')

            # Rename columns
            df.rename(columns={
                'time': 'datetime',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'tick_volume': 'Volume',
                'spread': 'Spread',
                'real_volume': 'Real_Volume'
            }, inplace=True)

            # Set datetime as index
            df.set_index('datetime', inplace=True)

            logger.info(f"Extracted {len(df)} bars for {symbol} ({timeframe})")

            return df

        except Exception as e:
            logger.error(f"Error extracting data: {e}")
            return None

    def extract_ticks(
        self,
        symbol: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        count: int = 10000
    ) -> Optional[pd.DataFrame]:
        """
        Extract tick data

        Args:
            symbol: Symbol name
            start_date: Start date
            end_date: End date
            count: Number of ticks

        Returns:
            DataFrame with tick data
        """
        if not self.connected:
            logger.error("Not connected to MT5")
            return None

        try:
            if start_date is None:
                start_date = datetime.now() - timedelta(days=1)
            if end_date is None:
                end_date = datetime.now()

            # Get ticks
            ticks = mt5.copy_ticks_range(symbol, start_date, end_date, mt5.COPY_TICKS_ALL)

            if ticks is None or len(ticks) == 0:
                logger.error(f"Failed to get ticks for {symbol}")
                return None

            # Convert to DataFrame
            df = pd.DataFrame(ticks)

            # Convert time to datetime
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df.rename(columns={'time': 'datetime'}, inplace=True)
            df.set_index('datetime', inplace=True)

            logger.info(f"Extracted {len(df)} ticks for {symbol}")

            return df

        except Exception as e:
            logger.error(f"Error extracting ticks: {e}")
            return None

    def extract_all_symbols(
        self,
        timeframes: List[str],
        output_dir: str = "data/raw",
        days: int = 365
    ):
        """
        Extract data for all configured symbols

        Args:
            timeframes: List of timeframes
            output_dir: Output directory
            days: Number of days to extract
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        start_date = datetime.now() - timedelta(days=days)
        end_date = datetime.now()

        # Get all symbols from config
        all_symbols = []
        for category, symbols in self.config['symbols'].items():
            all_symbols.extend(symbols)

        logger.info(f"Extracting data for {len(all_symbols)} symbols, {len(timeframes)} timeframes")

        for symbol in all_symbols:
            logger.info(f"Processing {symbol}...")

            # Get symbol info
            info = self.get_symbol_info(symbol)
            if info is None:
                logger.warning(f"Skipping {symbol} - not available")
                continue

            for timeframe in timeframes:
                # Extract OHLCV
                df = self.extract_ohlcv(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_date=start_date,
                    end_date=end_date
                )

                if df is not None and len(df) > 0:
                    # Save to file
                    filename = f"{symbol.replace(' ', '_')}_{timeframe}.parquet"
                    filepath = output_path / filename

                    df.to_parquet(filepath, compression='snappy')
                    logger.info(f"Saved {filepath} ({len(df)} rows)")

            # Extract tick data if enabled
            if self.config['extraction'].get('use_tick_data', False):
                ticks = self.extract_ticks(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date
                )

                if ticks is not None and len(ticks) > 0:
                    filename = f"{symbol.replace(' ', '_')}_TICKS.parquet"
                    filepath = output_path / filename
                    ticks.to_parquet(filepath, compression='snappy')
                    logger.info(f"Saved {filepath} ({len(ticks)} rows)")

        logger.info("Extraction complete!")

    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()


def main():
    """Main function for CLI usage"""
    import argparse

    parser = argparse.ArgumentParser(description='Extract data from MT5')
    parser.add_argument('--symbol', type=str, help='Symbol to extract')
    parser.add_argument('--timeframe', type=str, default='M1', help='Timeframe')
    parser.add_argument('--days', type=int, default=365, help='Number of days')
    parser.add_argument('--all', action='store_true', help='Extract all symbols')
    parser.add_argument('--config', type=str, default='config/config.yaml', help='Config file')

    args = parser.parse_args()

    # Setup logger
    logger.add("logs/extraction.log", rotation="100 MB")

    with MT5Extractor(args.config) as extractor:
        if args.all:
            timeframes = extractor.config['extraction']['timeframes']
            extractor.extract_all_symbols(timeframes, days=args.days)
        elif args.symbol:
            start_date = datetime.now() - timedelta(days=args.days)
            df = extractor.extract_ohlcv(
                symbol=args.symbol,
                timeframe=args.timeframe,
                start_date=start_date
            )
            if df is not None:
                print(df.head())
                print(f"\nTotal rows: {len(df)}")
        else:
            # Show available symbols
            symbols = extractor.get_symbols("Volatility")
            print("Available symbols:")
            for s in symbols[:20]:
                print(f"  - {s}")


if __name__ == "__main__":
    main()
