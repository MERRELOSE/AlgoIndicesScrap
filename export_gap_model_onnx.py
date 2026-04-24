#!/usr/bin/env python3
"""
Train a FINAL XGBoost model on all weekend features and export to ONNX.

Also dumps:
- feature_names.txt  : exact column order (critical for MQL5 to feed correctly)
- validation.csv     : a few (features, proba_python, proba_onnx) rows for MQL5 sanity-check
- training_stats.txt : insample metrics of the final model
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

import lightgbm as lgb
from sklearn.metrics import roc_auc_score, accuracy_score

# ONNX tooling (LightGBM has the most stable converter)
from onnxmltools.convert.lightgbm.convert import convert as convert_lgb
from onnxmltools.convert.common.data_types import FloatTensorType
import onnxruntime as ort

from forex.src.gap_model import FEATURE_COLS, _prep_xy


def _lgb_params() -> dict:
    """LightGBM params equivalent to our XGB defaults."""
    return dict(
        n_estimators=400,
        max_depth=4,
        num_leaves=15,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_samples=8,
        reg_alpha=0.1,
        reg_lambda=1.0,
        objective="binary",
        verbose=-1,
    )


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{level: <7}</level> {message}")

    feat_path = Path("forex/data/gaps/weekend_features.parquet")
    df = pd.read_parquet(feat_path).sort_index()
    df = df.dropna(subset=FEATURE_COLS + ["symbol", "y"]).copy()
    logger.info(f"Training set: {len(df)} rows, {df['symbol'].nunique()} symbols")

    X, y = _prep_xy(df)
    original_feature_names = X.columns.tolist()
    logger.info(f"Features ({len(original_feature_names)}): {original_feature_names}")

    model = lgb.LGBMClassifier(**_lgb_params())
    model.fit(X, y)
    proba_native = model.predict_proba(X)[:, 1]
    auc = roc_auc_score(y, proba_native)
    acc = accuracy_score(y, (proba_native >= 0.5).astype(int))
    logger.info(f"In-sample AUC={auc:.3f} accuracy={acc:.3f} "
                f"(expect higher than walk-forward due to training fit)")

    # --- ONNX export ---
    out_dir = Path("forex/models"); out_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = out_dir / "weekend_gap.onnx"

    initial_type = [("input", FloatTensorType([None, len(original_feature_names)]))]
    onnx_model = convert_lgb(model, initial_types=initial_type, target_opset=13,
                             zipmap=False)
    with open(onnx_path, "wb") as f:
        f.write(onnx_model.SerializeToString())
    logger.info(f"ONNX saved to {onnx_path} ({onnx_path.stat().st_size} bytes)")

    # --- Validate ONNX matches LightGBM on sample rows ---
    sess = ort.InferenceSession(str(onnx_path))
    onnx_out = sess.run(None, {"input": X.astype(np.float32).values})
    # LightGBM-ONNX (zipmap=False): [predictions, probabilities (2D array)]
    proba_onnx = onnx_out[1]
    proba_onnx_up = proba_onnx[:, 1] if proba_onnx.ndim == 2 else np.array([d[1] for d in proba_onnx])

    diff = np.abs(proba_native - proba_onnx_up)
    logger.info(f"ONNX vs LightGBM: max |diff|={diff.max():.2e}, mean={diff.mean():.2e}")
    if diff.max() > 1e-4:
        logger.warning("ONNX output differs meaningfully - investigate")
    else:
        logger.info("ONNX output matches LightGBM ✓")
    proba_xgb = proba_native  # rename for downstream code

    # --- Save metadata ---
    (out_dir / "feature_names.txt").write_text("\n".join(original_feature_names), encoding="utf-8")
    logger.info(f"Feature order saved to {out_dir / 'feature_names.txt'}")

    # --- Dump validation samples for MQL5 sanity check ---
    sample_idx = np.random.default_rng(42).choice(len(X), size=10, replace=False)
    sample = X.iloc[sample_idx].copy()
    sample["proba_python"] = proba_xgb[sample_idx]
    sample["proba_onnx"] = proba_onnx_up[sample_idx]
    sample["y_true"] = y.iloc[sample_idx].values
    sample.to_csv(out_dir / "validation_samples.csv")
    logger.info(f"10 validation rows saved to {out_dir / 'validation_samples.csv'}")

    # Summary
    (out_dir / "training_stats.txt").write_text(
        f"Training rows: {len(df)}\n"
        f"Features: {len(original_feature_names)}\n"
        f"In-sample AUC: {auc:.4f}\n"
        f"In-sample Acc: {acc:.4f}\n"
        f"Feature order: {original_feature_names}\n",
        encoding="utf-8"
    )


if __name__ == "__main__":
    main()
