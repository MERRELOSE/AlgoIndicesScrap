#!/usr/bin/env python3
"""
Script pour extraire rapidement les données multi-timeframe
"""
import asyncio
from pathlib import Path
from src.extractors.deriv_api_extractor import DerivAPIExtractor


async def extract_all_data():
    """Extrait les données pour Crash 500 sur 3 timeframes"""

    # Configuration
    symbol = 'Crash 500 Index'
    timeframes = ['M15', 'H1', 'H4']
    days = 365

    print("="*70)
    print(" " * 15 + "EXTRACTION MULTI-TIMEFRAME")
    print("="*70)
    print(f"\n📊 Symbol: {symbol}")
    print(f"⏰ Timeframes: {', '.join(timeframes)}")
    print(f"📅 Period: {days} days")
    print("\n" + "="*70 + "\n")

    # Créer le dossier data/raw
    output_dir = Path('data/raw')
    output_dir.mkdir(parents=True, exist_ok=True)

    # Créer l'extracteur
    extractor = DerivAPIExtractor()

    try:
        # Se connecter une fois
        await extractor.connect()

        # Extraire chaque timeframe
        for i, tf in enumerate(timeframes, 1):
            print(f"[{i}/{len(timeframes)}] Extracting {symbol} - {tf}...")

            df = await extractor.extract_ohlcv(symbol, tf, days)

            if df is not None and len(df) > 0:
                # Sauvegarder
                filename = f"{symbol.replace(' ', '_')}_{tf}.parquet"
                filepath = output_dir / filename
                df.to_parquet(filepath, compression='snappy')

                print(f"    ✅ Saved: {filepath}")
                print(f"    📊 Candles: {len(df)}")
                print(f"    📅 From {df.index[0]} to {df.index[-1]}")
                print()
            else:
                print(f"    ❌ Failed to extract {tf}")
                print()

            # Pause entre les requêtes
            if i < len(timeframes):
                await asyncio.sleep(1)

        # Déconnecter
        await extractor.disconnect()

        print("="*70)
        print(" " * 20 + "EXTRACTION COMPLETE!")
        print("="*70)
        print("\n✅ All data extracted successfully!")
        print(f"📁 Location: {output_dir.absolute()}")
        print("\n🚀 Next step: Run the multi-timeframe LSTM notebook")
        print("   jupyter notebook notebooks/04_multi_timeframe_lstm.ipynb")
        print("="*70)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        await extractor.disconnect()


if __name__ == "__main__":
    asyncio.run(extract_all_data())
