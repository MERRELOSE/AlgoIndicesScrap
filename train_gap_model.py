#!/usr/bin/env python3
"""
Train the weekend gap direction classifier and evaluate OOS.

Usage:
  python train_gap_model.py
  python train_gap_model.py --threshold 0.60
"""

from __future__ import annotations

import argparse
import sys
from loguru import logger

from forex.src.gap_model import walk_forward_eval, threshold_sweep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.55)
    ap.add_argument("--splits", type=int, default=5)
    ap.add_argument("--embargo", type=int, default=4)
    args = ap.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{level: <7}</level> {message}")

    res = walk_forward_eval(
        n_splits=args.splits,
        embargo=args.embargo,
        proba_threshold=args.threshold,
    )
    if not res:
        logger.error("Walk-forward failed.")
        return

    logger.info("\n--- Threshold sweep ---")
    sweep = threshold_sweep()
    if not sweep.empty:
        print(sweep.to_string(index=False))

    logger.info("\nOOS predictions saved to forex/reports/weekend_gap_oos_preds.csv")
    logger.info("Fold stats saved to forex/reports/weekend_gap_folds.csv")


if __name__ == "__main__":
    main()
