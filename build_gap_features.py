#!/usr/bin/env python3
"""Build weekend-gap training features for the validated metals set."""

import sys
from loguru import logger
import MetaTrader5 as mt5

from forex.src.gap_features import build_features_multi


VALIDATED_METALS = ["XAUUSD", "XAGUSD", "XAGEUR"]


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{level: <7}</level> {message}")

    df = build_features_multi(VALIDATED_METALS, years=5.0)
    mt5.shutdown()
    if df is None or df.empty:
        logger.error("No features built")
        return
    logger.info(f"\nFeature matrix: {df.shape}")
    logger.info(f"Symbols: {df['symbol'].value_counts().to_dict()}")
    logger.info(f"Target distribution: y=+1 {(df['y']==1).mean():.2%} | y=-1 {(df['y']==-1).mean():.2%}")
    logger.info(f"Mean |gap|: {df['gap_pct'].abs().mean():.3f}%")


if __name__ == "__main__":
    main()
