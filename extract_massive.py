#!/usr/bin/env python3
"""
Script d'extraction massive pour contourner la limite de 5000 candles.

Stratégie:
- Faire plusieurs appels API en décalant la date de fin
- Combiner tous les batches
- Supprimer les doublons
- Obtenir 20,000-30,000 candles au lieu de 5,000

Usage:
    python extract_massive.py --symbol "Crash 500 Index" --timeframe H4 --total-candles 20000
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
from loguru import logger

# Add src to path
sys.path.append(str(Path.cwd()))

from src.extractors.deriv_api_extractor import DerivAPIExtractor


class MassiveExtractor:
    """Extract large amounts of historical data by making multiple API calls"""

    # Granularity mapping (same as DerivAPIExtractor)
    GRANULARITY_MAP = {
        'M1': 60, 'M5': 300, 'M15': 900,
        'M30': 1800, 'H1': 3600, 'H4': 14400, 'D1': 86400,
    }

    def __init__(self):
        self.extractor = DerivAPIExtractor()

    def calculate_batches_needed(self, timeframe: str, total_candles: int) -> int:
        """
        Calculate how many API calls needed to get desired number of candles

        API limit is 5000 candles per call
        """
        max_per_call = 5000
        return (total_candles + max_per_call - 1) // max_per_call

    def calculate_days_per_batch(self, timeframe: str) -> int:
        """Calculate how many days worth of data in 5000 candles"""
        granularity = self.GRANULARITY_MAP[timeframe]
        candles_per_day = 86400 // granularity
        days_for_5000 = 5000 // candles_per_day
        return max(days_for_5000, 1)

    async def extract_massive(
        self,
        symbol: str,
        timeframe: str = 'H4',
        total_candles: int = 20000,
        delay_between_calls: float = 2.0
    ) -> pd.DataFrame:
        """
        Extract large amount of historical data

        Args:
            symbol: Symbol name (e.g., 'Crash 500 Index')
            timeframe: Timeframe (M1, M5, M15, H1, H4, D1)
            total_candles: Total number of candles to fetch (default: 20,000)
            delay_between_calls: Seconds to wait between API calls (default: 2.0)

        Returns:
            DataFrame with all historical data
        """
        logger.info(f"Starting massive extraction for {symbol} {timeframe}")
        logger.info(f"Target: {total_candles} candles")

        # Calculate batches needed
        num_batches = self.calculate_batches_needed(timeframe, total_candles)
        days_per_batch = self.calculate_days_per_batch(timeframe)

        logger.info(f"Will make {num_batches} API calls")
        logger.info(f"Approximately {days_per_batch} days per batch")

        # Connect once
        await self.extractor.connect()

        all_data = []
        total_extracted = 0

        for batch_num in range(num_batches):
            # Calculate how many days to request for this batch
            # Start from most recent and go backwards
            days_offset = batch_num * days_per_batch
            days_to_request = days_per_batch

            logger.info(f"\n[Batch {batch_num + 1}/{num_batches}]")
            logger.info(f"  Requesting {days_to_request} days (offset: {days_offset} days from now)")

            try:
                # Extract this batch
                df_batch = await self.extractor.extract_ohlcv(
                    symbol=symbol,
                    timeframe=timeframe,
                    days=days_to_request
                )

                if df_batch is not None and len(df_batch) > 0:
                    # Adjust timestamps to go further back in time
                    # Each batch should be older than the previous one
                    if batch_num > 0 and len(all_data) > 0:
                        # Get the oldest timestamp from previous batches
                        oldest_existing = min([df.index.min() for df in all_data])

                        # Only keep data older than what we already have
                        df_batch = df_batch[df_batch.index < oldest_existing]

                    if len(df_batch) > 0:
                        all_data.append(df_batch)
                        total_extracted += len(df_batch)

                        logger.info(f"  ✅ Extracted {len(df_batch)} candles")
                        logger.info(f"  📊 Total so far: {total_extracted} candles")
                        logger.info(f"  📅 Date range: {df_batch.index[0]} to {df_batch.index[-1]}")
                    else:
                        logger.warning(f"  ⚠️ No new data in this batch (overlaps with existing)")
                else:
                    logger.error(f"  ❌ Failed to extract batch {batch_num + 1}")

                # Stop if we have enough data
                if total_extracted >= total_candles:
                    logger.info(f"\n✅ Target reached! Got {total_extracted} candles")
                    break

                # Delay between calls to avoid rate limiting
                if batch_num < num_batches - 1:
                    logger.info(f"  ⏳ Waiting {delay_between_calls}s before next call...")
                    await asyncio.sleep(delay_between_calls)

            except Exception as e:
                logger.error(f"  ❌ Error in batch {batch_num + 1}: {e}")
                continue

        # Disconnect
        await self.extractor.disconnect()

        if not all_data:
            logger.error("No data extracted!")
            return None

        # Combine all batches
        logger.info("\n📊 Combining all batches...")
        df_combined = pd.concat(all_data)

        # Sort by index and remove duplicates
        df_combined = df_combined.sort_index()
        df_combined = df_combined[~df_combined.index.duplicated(keep='first')]

        logger.info(f"✅ Final dataset: {len(df_combined)} candles")
        logger.info(f"📅 Date range: {df_combined.index[0]} to {df_combined.index[-1]}")
        logger.info(f"📈 Coverage: {(df_combined.index[-1] - df_combined.index[0]).days} days")

        return df_combined

    async def extract_multi_timeframe_massive(
        self,
        symbol: str,
        timeframes: list = ['M15', 'H1', 'H4'],
        total_candles: int = 20000,
        output_dir: str = 'data/raw'
    ):
        """
        Extract massive data for multiple timeframes and save to files

        Args:
            symbol: Symbol name
            timeframes: List of timeframes to extract
            total_candles: Target number of candles per timeframe
            output_dir: Directory to save files
        """
        logger.info("="*70)
        logger.info(" " * 15 + "MASSIVE MULTI-TIMEFRAME EXTRACTION")
        logger.info("="*70)
        logger.info(f"\n📊 Symbol: {symbol}")
        logger.info(f"⏰ Timeframes: {', '.join(timeframes)}")
        logger.info(f"🎯 Target: {total_candles} candles per timeframe")
        logger.info("\n" + "="*70 + "\n")

        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        results = {}

        for i, tf in enumerate(timeframes, 1):
            logger.info(f"\n{'='*70}")
            logger.info(f"[{i}/{len(timeframes)}] Extracting {symbol} - {tf}")
            logger.info(f"{'='*70}")

            try:
                df = await self.extract_massive(
                    symbol=symbol,
                    timeframe=tf,
                    total_candles=total_candles
                )

                if df is not None and len(df) > 0:
                    # Save to file
                    filename = f"{symbol.replace(' ', '_')}_{tf}_massive.parquet"
                    filepath = output_path / filename
                    df.to_parquet(filepath, compression='snappy')

                    results[tf] = {
                        'candles': len(df),
                        'filepath': filepath,
                        'date_range': (df.index[0], df.index[-1])
                    }

                    logger.info(f"\n✅ Saved: {filepath}")
                    logger.info(f"📊 Candles: {len(df)}")
                    logger.info(f"📅 From {df.index[0]} to {df.index[-1]}")
                else:
                    logger.error(f"\n❌ Failed to extract {tf}")
                    results[tf] = None

            except Exception as e:
                logger.error(f"\n❌ Error extracting {tf}: {e}")
                results[tf] = None

        # Summary
        logger.info("\n" + "="*70)
        logger.info(" " * 25 + "EXTRACTION COMPLETE")
        logger.info("="*70)

        successful = sum(1 for v in results.values() if v is not None)
        logger.info(f"\n✅ Successful: {successful}/{len(timeframes)}")

        for tf, result in results.items():
            if result:
                logger.info(f"\n{tf}:")
                logger.info(f"  📊 Candles: {result['candles']}")
                logger.info(f"  📁 File: {result['filepath']}")
            else:
                logger.info(f"\n{tf}: ❌ Failed")

        logger.info("\n" + "="*70)
        logger.info("\n🚀 Next step: Use these files in the improved LSTM notebook")
        logger.info("="*70)

        return results


async def main():
    """Main function with CLI arguments"""
    import argparse

    parser = argparse.ArgumentParser(description='Extract massive historical data from Deriv API')
    parser.add_argument('--symbol', type=str, default='Crash 500 Index', help='Symbol to extract')
    parser.add_argument('--timeframe', type=str, default='H4', help='Timeframe (M15, H1, H4, etc.)')
    parser.add_argument('--total-candles', type=int, default=20000, help='Total candles to extract')
    parser.add_argument('--multi', action='store_true', help='Extract multiple timeframes (M15, H1, H4)')
    parser.add_argument('--output-dir', type=str, default='data/raw', help='Output directory')

    args = parser.parse_args()

    # Setup logger
    logger.add("logs/massive_extraction.log", rotation="100 MB")

    extractor = MassiveExtractor()

    if args.multi:
        # Multi-timeframe extraction
        await extractor.extract_multi_timeframe_massive(
            symbol=args.symbol,
            timeframes=['M15', 'H1', 'H4'],
            total_candles=args.total_candles,
            output_dir=args.output_dir
        )
    else:
        # Single timeframe extraction
        df = await extractor.extract_massive(
            symbol=args.symbol,
            timeframe=args.timeframe,
            total_candles=args.total_candles
        )

        if df is not None:
            # Save to file
            output_path = Path(args.output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            filename = f"{args.symbol.replace(' ', '_')}_{args.timeframe}_massive.parquet"
            filepath = output_path / filename

            df.to_parquet(filepath, compression='snappy')
            logger.info(f"\n✅ Saved to: {filepath}")


if __name__ == "__main__":
    asyncio.run(main())
