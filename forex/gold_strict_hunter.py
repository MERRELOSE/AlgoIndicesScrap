#!/usr/bin/env python3
"""
Gold Strict Recipe Hunter - XAUUSD H1
======================================

Approche plus stricte que run_behavior.py:
  - Triple split temporel: train 50% / val 25% / test 25%
  - Une recette est gardee SI validee sur val ET test (double OOS)
  - Recettes jusqu'a 4 features (vs 3 dans le pipeline de base)
  - Focus WR eleve: event_rate OOS >= 45% pour LONG
  - Compatible avec Gold_Behavior_EA_v1 (meme RR 2:1, meme horizon 24)

Output: forex/reports/gold_strict_LONG.csv et gold_strict_SHORT.csv
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path
from itertools import combinations

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forex.src.features import atr                                    # noqa: E402
from forex.src.behavior.events import EventConfig, detect_big_moves   # noqa: E402
from forex.src.behavior.context import build_context, discretize      # noqa: E402

warnings.filterwarnings("ignore")


# ============================================================
# Parametres stricts
# ============================================================
PAIR = "XAUUSD"
TF = "H1"
CFG = EventConfig(target_atr=2.0, stop_atr=1.0, horizon=24)

# Seuils train
TRAIN_MIN_N = 60
TRAIN_SEED_LIFT = 1.03     # pour singles (graines, pour pouvoir combiner)
TRAIN_COMBO_LIFT = 1.20    # pour combos (filtre strict)
TRAIN_P_MAX_SEED = 0.20    # singles: peu strict (sinon on rate des graines utiles)
TRAIN_P_MAX_COMBO = 0.02   # combos: strict

# Seuils OOS (doivent PASSER sur val ET test)
OOS_MIN_N = 20
OOS_MIN_LIFT = 1.15
OOS_MIN_RATE_LONG = 0.45   # WR min 45% sur LONG (base ~34%)
OOS_MIN_RATE_SHORT = 0.15  # WR min 15% sur SHORT (base ~9%)

MAX_COMBO_SIZE = 4  # jusqu'a 4 features


# ============================================================
# Utilitaires
# ============================================================
def masks_by_value(X: pd.DataFrame) -> dict:
    """Precompute boolean masks per (value) across all columns."""
    value_to_col = {}
    masks = {}
    for col in X.columns:
        for v in X[col].unique():
            value_to_col[v] = col
            masks[v] = (X[col] == v).values
    return value_to_col, masks


def stats_for(mask: np.ndarray, y: np.ndarray, base: float):
    n = int(mask.sum())
    if n == 0:
        return 0, 0.0, 0.0, 0.0
    ev = y[mask]
    rate = ev.mean()
    lift = rate / base if base > 0 else 0.0
    edge = rate - base
    return n, rate, lift, edge


def binomtest_pvalue(succ: int, n: int, p0: float) -> float:
    from scipy import stats as sps
    try:
        return sps.binomtest(succ, n, p0).pvalue
    except Exception:
        return 1.0


# ============================================================
# Pipeline
# ============================================================
def run():
    # -- Load data --
    data_path = ROOT / "forex" / "data" / "raw" / f"{PAIR}_{TF}.parquet"
    htf_path = ROOT / "forex" / "data" / "raw" / f"{PAIR}_H4.parquet"
    if not data_path.exists():
        print(f"ERROR: {data_path} not found")
        return

    df = pd.read_parquet(data_path)
    htf = pd.read_parquet(htf_path) if htf_path.exists() else None
    print(f"Loaded {PAIR} {TF}: {len(df)} bars | {df.index[0]} -> {df.index[-1]}")

    df["atr_14"] = atr(df["High"], df["Low"], df["Close"], 14)

    # -- Events --
    events = detect_big_moves(df, CFG)
    base_long = events["event_long"].dropna().mean()
    base_short = events["event_short"].dropna().mean()
    print(f"Base rates: long_tp={base_long:.2%}  short_tp={base_short:.2%}")

    # -- Context --
    htf_close = htf["Close"] if htf is not None else None
    ctx = build_context(df, htf_close=htf_close)
    bins = discretize(ctx, n_bins=4)
    print(f"Context: {bins.shape}")

    # -- Triple split 50/25/25 --
    n_total = len(bins)
    split1 = int(0.50 * n_total)
    split2 = int(0.75 * n_total)
    idx_train = bins.index[:split1]
    idx_val = bins.index[split1:split2]
    idx_test = bins.index[split2:]
    print(f"Splits: train={len(idx_train)} val={len(idx_val)} test={len(idx_test)}")

    for side in ("long", "short"):
        print(f"\n=== Discovery [{side.upper()}] ===")
        ev_col = f"event_{side}"

        # Align bins and events on common index, then split
        ev_all = events[ev_col].dropna()
        common = bins.index.intersection(ev_all.index)

        idx_tr = common[common <= idx_train[-1]]
        idx_va = common[(common > idx_train[-1]) & (common <= idx_val[-1])]
        idx_te = common[common > idx_val[-1]]

        b_train = bins.loc[idx_tr]
        b_val = bins.loc[idx_va]
        b_test = bins.loc[idx_te]
        y_train = ev_all.loc[idx_tr].astype(int).values
        y_val = ev_all.loc[idx_va].astype(int).values
        y_test = ev_all.loc[idx_te].astype(int).values

        base_tr = y_train.mean() if len(y_train) > 0 else 0
        base_va = y_val.mean() if len(y_val) > 0 else 0
        base_te = y_test.mean() if len(y_test) > 0 else 0
        print(f"  base rates: train={base_tr:.2%} val={base_va:.2%} test={base_te:.2%}")

        if base_tr <= 0:
            print("  No events on train, skip.")
            continue

        v2c_tr, masks_tr = masks_by_value(b_train)
        v2c_va, masks_va = masks_by_value(b_val)
        v2c_te, masks_te = masks_by_value(b_test)

        # Step 1: singles - show top 10 by lift
        all_singles = []
        for v, m_tr in masks_tr.items():
            n, rate, lift, edge = stats_for(m_tr, y_train, base_tr)
            if n < TRAIN_MIN_N:
                continue
            all_singles.append((v, n, rate, lift))
        all_singles.sort(key=lambda x: -x[3])
        print(f"  top 10 singles by lift: " + ", ".join(
            f"{v}(n={n},r={r:.2f},L={l:.2f})" for v, n, r, l in all_singles[:10]))

        singles_kept = []
        for v, m_tr in masks_tr.items():
            n, rate, lift, edge = stats_for(m_tr, y_train, base_tr)
            if n < TRAIN_MIN_N or lift < TRAIN_SEED_LIFT:
                continue
            succ = int((y_train * m_tr).sum())
            p = binomtest_pvalue(succ, n, base_tr)
            if p > TRAIN_P_MAX_SEED:
                continue
            singles_kept.append(v)

        print(f"  singles seeds (kept): {len(singles_kept)}")

        # Step 2: combos (size 2, 3, 4) from singles pool only
        # Each combo must come from DIFFERENT columns
        all_recipes = []
        # keep singles too but with strict lift
        for v in singles_kept:
            m = masks_tr[v]
            n, rate, lift, edge = stats_for(m, y_train, base_tr)
            if lift >= TRAIN_COMBO_LIFT:
                succ = int((y_train * m).sum())
                p = binomtest_pvalue(succ, n, base_tr)
                if p <= TRAIN_P_MAX_COMBO:
                    all_recipes.append((v,))

        for size in range(2, MAX_COMBO_SIZE + 1):
            count = 0
            for combo in combinations(singles_kept, size):
                cols = {v2c_tr.get(v) for v in combo}
                if len(cols) != size:
                    continue
                mask = np.ones(len(y_train), dtype=bool)
                for v in combo:
                    mask &= masks_tr[v]
                n_ev = int(mask.sum())
                if n_ev < TRAIN_MIN_N:
                    continue
                n, rate, lift, edge = stats_for(mask, y_train, base_tr)
                # Exiger un lift plus eleve a mesure que la taille augmente
                if lift < TRAIN_COMBO_LIFT + 0.05 * (size - 2):
                    continue
                succ = int((y_train * mask).sum())
                p = binomtest_pvalue(succ, n, base_tr)
                if p > TRAIN_P_MAX_COMBO:
                    continue
                all_recipes.append(tuple(sorted(combo)))
                count += 1
            print(f"  combos size {size}: {count}")

        # Step 3: validate on val AND test
        min_rate = OOS_MIN_RATE_LONG if side == "long" else OOS_MIN_RATE_SHORT
        robust = []
        for combo in all_recipes:
            # Val
            if not all(v in masks_va for v in combo):
                continue
            m_va = np.ones(len(y_val), dtype=bool)
            for v in combo:
                m_va &= masks_va[v]
            n_va, rate_va, lift_va, edge_va = stats_for(m_va, y_val, base_va)
            if n_va < OOS_MIN_N or lift_va < OOS_MIN_LIFT or rate_va < min_rate:
                continue

            # Test
            if not all(v in masks_te for v in combo):
                continue
            m_te = np.ones(len(y_test), dtype=bool)
            for v in combo:
                m_te &= masks_te[v]
            n_te, rate_te, lift_te, edge_te = stats_for(m_te, y_test, base_te)
            if n_te < OOS_MIN_N or lift_te < OOS_MIN_LIFT or rate_te < min_rate:
                continue

            # Train stats
            m_tr = np.ones(len(y_train), dtype=bool)
            for v in combo:
                m_tr &= masks_tr[v]
            n_tr, rate_tr, lift_tr, edge_tr = stats_for(m_tr, y_train, base_tr)

            robust.append({
                "size": len(combo),
                "recipe": " & ".join(combo),
                "n_train": n_tr, "rate_train": rate_tr, "lift_train": lift_tr,
                "n_val": n_va, "rate_val": rate_va, "lift_val": lift_va,
                "n_test": n_te, "rate_test": rate_te, "lift_test": lift_te,
                "avg_oos_rate": (rate_va + rate_te) / 2,
                "min_oos_rate": min(rate_va, rate_te),
            })

        if not robust:
            print(f"  [{side.upper()}] NO robust recipes")
            continue

        df_r = pd.DataFrame(robust).sort_values(
            ["min_oos_rate", "avg_oos_rate"], ascending=False
        )
        print(f"\n  [{side.upper()}] {len(df_r)} ROBUST recipes (val AND test valid):")
        print(df_r.head(15).to_string(index=False, float_format=lambda x: f"{x:.3f}"))

        # Save
        out_path = ROOT / "forex" / "reports" / f"gold_strict_{side.upper()}.csv"
        df_r.to_csv(out_path, index=False)
        print(f"  saved -> {out_path.name}")


if __name__ == "__main__":
    run()
