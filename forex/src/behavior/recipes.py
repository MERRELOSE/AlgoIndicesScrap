#!/usr/bin/env python3
"""
Recipe discovery: find small combinations of binned context features that occur
disproportionately often before big-move events.

Approach:
  1. For each single feature-value pair, compute P(event | value) and test
     via binomial test against the base rate.
  2. Combine only the top single-feature signals into pairs and triples,
     keeping only those that (a) occur >= min_occurrences times, (b) have
     statistically significant lift, (c) remain consistent when split into
     first half / second half of data.

Recipes are stored as sorted tuples of strings like
  ("rsi_14_q1", "sess_london_1", "atr_ratio_q4")
which are interpretable immediately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterable, Optional

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class Recipe:
    features: tuple                  # sorted tuple of binned feature values
    direction: str                   # "long" or "short"
    n: int = 0
    base_rate: float = 0.0
    event_rate: float = 0.0
    lift: float = 0.0               # event_rate / base_rate
    edge: float = 0.0               # event_rate - base_rate
    p_value: float = 1.0
    first_half_rate: float = 0.0
    second_half_rate: float = 0.0
    consistent: bool = False
    is_valid: bool = False

    def label(self) -> str:
        return " & ".join(self.features)


def _test_recipe(event_mask: np.ndarray, base_rate: float, half_split: int) -> tuple[int, float, float, float, float, bool]:
    n = len(event_mask)
    succ = int(event_mask.sum())
    if n < 30:
        return n, float("nan"), float("nan"), 1.0, float("nan"), False
    rate = succ / n
    # Binomial test (two-sided)
    try:
        p = stats.binomtest(succ, n, base_rate).pvalue
    except Exception:
        p = 1.0

    # Consistency: first-half and second-half same-direction lift
    fh = event_mask[:half_split]
    sh = event_mask[half_split:]
    fh_rate = fh.mean() if len(fh) >= 10 else rate
    sh_rate = sh.mean() if len(sh) >= 10 else rate

    consistent = (
        (fh_rate > base_rate and sh_rate > base_rate)
        or (fh_rate < base_rate and sh_rate < base_rate)
    )
    return n, rate, p, fh_rate, sh_rate, consistent


def discover_single_signals(
    bins: pd.DataFrame,
    events: pd.Series,
    direction: str,
    min_n: int = 50,
    p_max: float = 0.01,
    min_lift: float = 1.3,
) -> list[Recipe]:
    """
    Test every single feature-value pair. Keep those that pass.
    Much faster than mining pairs/triples naively.
    """
    common_idx = bins.index.intersection(events.dropna().index)
    X = bins.loc[common_idx]
    y = events.loc[common_idx].astype(int).values
    base = y.mean()
    if base <= 0:
        return []

    half = len(y) // 2
    out: list[Recipe] = []

    for col in X.columns:
        for val, mask in X[col].groupby(X[col]).groups.items():
            ev = y[np.isin(common_idx, list(mask))]
            n, rate, p, fh, sh, consistent = _test_recipe(ev, base, half)
            if n < min_n:
                continue
            if rate <= 0:
                continue
            lift = rate / base
            if lift < min_lift:
                continue
            if p > p_max:
                continue

            r = Recipe(
                features=(val,), direction=direction,
                n=n, base_rate=base, event_rate=rate,
                lift=lift, edge=rate - base, p_value=p,
                first_half_rate=fh, second_half_rate=sh,
                consistent=consistent, is_valid=consistent,
            )
            out.append(r)
    out.sort(key=lambda r: r.lift, reverse=True)
    return out


def discover_combos(
    bins: pd.DataFrame,
    events: pd.Series,
    direction: str,
    seeds: list[Recipe],
    combo_size: int = 2,
    min_n: int = 30,
    p_max: float = 0.01,
    min_lift: float = 1.5,
) -> list[Recipe]:
    """
    Given single-feature seeds that already have lift, combine their values
    (taking at most one value per feature) into tuples of `combo_size` and
    test each combination. This keeps the search tractable and interpretable.
    """
    common_idx = bins.index.intersection(events.dropna().index)
    X = bins.loc[common_idx]
    y = events.loc[common_idx].astype(int).values
    base = y.mean()
    if base <= 0 or not seeds:
        return []
    half = len(y) // 2

    # Collect candidate (feature_col, value) from seeds
    # We must know which column each seed value belongs to. Rebuild that map.
    value_to_col = {}
    for col in X.columns:
        for v in X[col].unique():
            value_to_col[v] = col

    seed_values = [r.features[0] for r in seeds]
    # Remove seeds belonging to the same column when combining
    out: list[Recipe] = []

    # Pre-compute boolean masks for each seed value (speedup)
    masks = {v: (X[value_to_col[v]] == v).values for v in seed_values if v in value_to_col}

    for combo in combinations(seed_values, combo_size):
        # Must come from different columns
        cols = {value_to_col.get(v) for v in combo}
        if len(cols) != combo_size:
            continue
        mask = np.ones(len(y), dtype=bool)
        for v in combo:
            mask &= masks[v]
        if mask.sum() < min_n:
            continue
        ev = y[mask]
        n, rate, p, fh, sh, consistent = _test_recipe(ev, base, half)
        if n < min_n or rate <= 0:
            continue
        lift = rate / base
        if lift < min_lift or p > p_max:
            continue

        features_sorted = tuple(sorted(combo))
        r = Recipe(
            features=features_sorted, direction=direction,
            n=n, base_rate=base, event_rate=rate,
            lift=lift, edge=rate - base, p_value=p,
            first_half_rate=fh, second_half_rate=sh,
            consistent=consistent, is_valid=consistent,
        )
        out.append(r)

    out.sort(key=lambda r: r.lift, reverse=True)
    return out


def validate_out_of_sample(
    recipes: list[Recipe],
    bins_test: pd.DataFrame,
    events_test: pd.Series,
    min_n: int = 20,
) -> list[Recipe]:
    """
    Take recipes discovered on train data and recompute their stats on test data.
    Returns a new list with updated n / event_rate / lift and an `is_valid` flag
    set only when out-of-sample lift matches direction of the in-sample lift.
    """
    common_idx = bins_test.index.intersection(events_test.dropna().index)
    if common_idx.empty:
        return []
    X = bins_test.loc[common_idx]
    y = events_test.loc[common_idx].astype(int).values
    base = y.mean()
    if base <= 0:
        return []

    value_to_col = {}
    for col in X.columns:
        for v in X[col].unique():
            value_to_col[v] = col

    out: list[Recipe] = []
    for r in recipes:
        # Build mask
        mask = np.ones(len(y), dtype=bool)
        ok = True
        for v in r.features:
            if v not in value_to_col:
                ok = False; break
            mask &= (X[value_to_col[v]] == v).values
        if not ok:
            continue
        if mask.sum() < min_n:
            continue
        ev = y[mask]
        rate = ev.mean()
        lift = rate / base if base > 0 else 0
        # Same direction of lift as in-sample?
        same_direction = (
            (r.event_rate > r.base_rate and rate > base)
            or (r.event_rate < r.base_rate and rate < base)
        )
        r2 = Recipe(
            features=r.features, direction=r.direction,
            n=int(mask.sum()), base_rate=base, event_rate=rate,
            lift=lift, edge=rate - base,
            p_value=1.0,  # not recomputed here
            first_half_rate=r.first_half_rate, second_half_rate=r.second_half_rate,
            consistent=r.consistent,
            is_valid=same_direction and mask.sum() >= min_n,
        )
        out.append(r2)
    return out


def recipes_to_df(recipes: list[Recipe]) -> pd.DataFrame:
    rows = []
    for r in recipes:
        rows.append({
            "direction": r.direction,
            "size": len(r.features),
            "recipe": r.label(),
            "n": r.n,
            "base_rate": r.base_rate,
            "event_rate": r.event_rate,
            "lift": r.lift,
            "edge": r.edge,
            "p_value": r.p_value,
            "fh_rate": r.first_half_rate,
            "sh_rate": r.second_half_rate,
            "consistent": r.consistent,
            "is_valid": r.is_valid,
        })
    return pd.DataFrame(rows)
