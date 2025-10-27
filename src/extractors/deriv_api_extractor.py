"""
Deriv API Data Extractor - Extraction via l'API officielle Deriv
Alternative à MT5 - Plus simple et fonctionne sans MT5 installé
"""

import json
import asyncio
import websockets
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict
from loguru import logger
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class DerivAPIExtractor:
    """Extracteur de données via l'API Deriv WebSocket"""

    # Mapping des symboles MT5 vers l'API Deriv
    SYMBOL_MAP = {
        'Volatility 10 Index': 'R_10',
        'Volatility 10 (1s) Index': '1HZ10V',
        'Volatility 25 Index': 'R_25',
        'Volatility 25 (1s) Index': '1HZ25V',
        'Volatility 50 Index': 'R_50',
        'Volatility 50 (1s) Index': '1HZ50V',
        'Volatility 75 Index': 'R_75',
        'Volatility 75 (1s) Index': '1HZ75V',
        'Volatility 100 Index': 'R_100',
        'Volatility 100 (1s) Index': '1HZ100V',
        'Crash 500 Index': 'CRASH500',
        'Crash 1000 Index': 'CRASH1000',
        'Boom 500 Index': 'BOOM500',
        'Boom 1000 Index': 'BOOM1000',
        'Step Index': 'stpRNG',
    }

    # Mapping des timeframes
    GRANULARITY_MAP = {
        'M1': 60,
        'M5': 300,
        'M15': 900,
        'M30': 1800,
        'H1': 3600,
        'H4': 14400,
        'D1': 86400,
    }

    def __init__(self, api_token: Optional[str] = None):
        """
        Initialize Deriv API Extractor

        Args:
            api_token: API token (optional, can use without token for public data)
        """
        self.api_token = api_token or os.getenv('DERIV_API_TOKEN')
        self.ws_url = "wss://ws.derivws.com/websockets/v3?app_id=1089"
        self.ws = None

        logger.info("Deriv API Extractor initialized")
        if not self.api_token:
            logger.warning("No API token provided - using public data only")

    async def connect(self):
        """Connect to Deriv WebSocket API"""
        try:
            self.ws = await websockets.connect(self.ws_url)
            logger.info("Connected to Deriv API")

            # Authorize if token is provided
            if self.api_token:
                await self.authorize()

            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    async def disconnect(self):
        """Disconnect from Deriv API"""
        if self.ws:
            await self.ws.close()
            logger.info("Disconnected from Deriv API")

    async def authorize(self):
        """Authorize with API token"""
        auth_request = {
            "authorize": self.api_token
        }
        await self.ws.send(json.dumps(auth_request))
        response = await self.ws.recv()
        data = json.loads(response)

        if 'error' in data:
            logger.error(f"Authorization failed: {data['error']['message']}")
            return False

        logger.info("Authorization successful")
        return True

    def get_deriv_symbol(self, symbol: str) -> str:
        """Convert MT5 symbol name to Deriv API symbol"""
        if symbol in self.SYMBOL_MAP:
            return self.SYMBOL_MAP[symbol]
        return symbol

    async def get_candles(
        self,
        symbol: str,
        granularity: int,
        count: int
    ) -> Optional[List[Dict]]:
        """
        Get candlestick data from Deriv API

        Args:
            symbol: Deriv symbol (e.g., 'R_100')
            granularity: Candle size in seconds
            count: Number of candles

        Returns:
            List of candles
        """
        request = {
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "granularity": granularity,
            "start": 1,
            "style": "candles"
        }

        await self.ws.send(json.dumps(request))
        response = await self.ws.recv()
        data = json.loads(response)

        if 'error' in data:
            logger.error(f"Error getting candles: {data['error']['message']}")
            return None

        return data.get('candles', [])

    async def extract_ohlcv(
        self,
        symbol: str,
        timeframe: str = 'M1',
        days: int = 30
    ) -> Optional[pd.DataFrame]:
        """
        Extract OHLCV data

        Args:
            symbol: Symbol name (MT5 format or Deriv format)
            timeframe: Timeframe (M1, M5, M15, H1, H4, D1)
            days: Number of days to extract

        Returns:
            DataFrame with OHLCV data
        """
        # Convert symbol
        deriv_symbol = self.get_deriv_symbol(symbol)

        # Get granularity
        if timeframe not in self.GRANULARITY_MAP:
            logger.error(f"Invalid timeframe: {timeframe}")
            return None

        granularity = self.GRANULARITY_MAP[timeframe]

        # Calculate number of candles
        seconds_per_day = 86400
        candles_per_day = seconds_per_day // granularity
        count = min(candles_per_day * days, 5000)  # API limit

        logger.info(f"Extracting {symbol} ({deriv_symbol}) - {timeframe} - {days} days ({count} candles)")

        try:
            # Connect if not connected
            if not self.ws:
                await self.connect()

            # Get candles
            candles = await self.get_candles(deriv_symbol, granularity, count)

            if not candles:
                logger.error("No data received")
                return None

            # Convert to DataFrame
            df = pd.DataFrame(candles)

            # Rename columns
            df.rename(columns={
                'epoch': 'timestamp',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close'
            }, inplace=True)

            # Convert timestamp to datetime
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
            df.set_index('datetime', inplace=True)

            # Drop timestamp column
            df.drop('timestamp', axis=1, inplace=True)

            # Add Volume (not provided by API for synthetic indices)
            df['Volume'] = 0

            logger.info(f"Extracted {len(df)} candles for {symbol}")

            return df

        except Exception as e:
            logger.error(f"Error extracting data: {e}")
            return None

    async def extract_multiple_symbols(
        self,
        symbols: List[str],
        timeframe: str = 'M1',
        days: int = 30,
        output_dir: str = 'data/raw'
    ):
        """
        Extract data for multiple symbols

        Args:
            symbols: List of symbol names
            timeframe: Timeframe
            days: Number of days
            output_dir: Output directory
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Connect once
        await self.connect()

        for symbol in symbols:
            logger.info(f"Processing {symbol}...")

            df = await self.extract_ohlcv(symbol, timeframe, days)

            if df is not None and len(df) > 0:
                # Save to file
                filename = f"{symbol.replace(' ', '_')}_{timeframe}.parquet"
                filepath = output_path / filename

                df.to_parquet(filepath, compression='snappy')
                logger.info(f"Saved {filepath} ({len(df)} rows)")

        await self.disconnect()

        logger.info("Extraction complete!")


async def main():
    """Example usage"""
    import argparse

    parser = argparse.ArgumentParser(description='Extract data from Deriv API')
    parser.add_argument('--symbol', type=str, default='Volatility 100 Index', help='Symbol to extract')
    parser.add_argument('--timeframe', type=str, default='M1', help='Timeframe')
    parser.add_argument('--days', type=int, default=30, help='Number of days')
    parser.add_argument('--all', action='store_true', help='Extract all configured symbols')

    args = parser.parse_args()

    # Setup logger
    logger.add("logs/extraction.log", rotation="100 MB")

    # Create extractor
    extractor = DerivAPIExtractor()

    if args.all:
        # Extract all major synthetic indices
        symbols = [
            'Volatility 10 Index',
            'Volatility 25 Index',
            'Volatility 75 Index',
            'Volatility 100 Index',
            'Crash 500 Index',
            'Boom 500 Index',
        ]
        await extractor.extract_multiple_symbols(symbols, args.timeframe, args.days)
    else:
        # Extract single symbol
        await extractor.connect()
        df = await extractor.extract_ohlcv(args.symbol, args.timeframe, args.days)

        if df is not None:
            print(f"\n{df.head()}")
            print(f"\nTotal rows: {len(df)}")

            # Save
            output_dir = Path('data/raw')
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{args.symbol.replace(' ', '_')}_{args.timeframe}.parquet"
            filepath = output_dir / filename
            df.to_parquet(filepath, compression='snappy')
            print(f"\nSaved to: {filepath}")

        await extractor.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
