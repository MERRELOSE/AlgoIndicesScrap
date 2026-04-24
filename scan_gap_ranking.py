"""
scan_gap_ranking.py
-------------------
Analyse les gaps weekend sur tous les marchés disponibles sur Exness/MT5.
Classe les marchés par rentabilité pour la stratégie straddle vendredi.

Usage:
    python scan_gap_ranking.py
    python scan_gap_ranking.py --years 3 --min-gaps 30
"""
import argparse
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[ERROR] MetaTrader5 non installé : pip install MetaTrader5")
    sys.exit(1)

# ---------------------------------------------------------------------------
# SYMBOLES À ANALYSER
# ---------------------------------------------------------------------------
SYMBOLS = {
    "Métaux":    ["XAUUSD", "XAGUSD", "XAGEUR", "XAUEUR", "XPTUSD", "XPDUSD"],
    "Forex":     ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD",
                  "USDCAD", "USDCHF", "EURJPY", "GBPJPY", "AUDJPY"],
    "Énergies":  ["USOIL", "UKOIL", "NATGAS"],
    "Indices":   ["US30", "US500", "NAS100", "GER40", "UK100", "JPN225", "AUS200"],
}

# ---------------------------------------------------------------------------
# HELPERS MT5
# ---------------------------------------------------------------------------

def init_mt5() -> bool:
    if not mt5.initialize():
        print(f"[ERROR] MT5 init failed: {mt5.last_error()}")
        return False
    info = mt5.account_info()
    if info:
        print(f"[MT5] Connecté — {info.server}  login={info.login}  devise={info.currency}")
    return True


def get_daily_bars(symbol: str, years: int) -> pd.DataFrame | None:
    """Retourne les barres D1 des `years` dernières années."""
    end   = datetime.utcnow()
    start = end - timedelta(days=365 * years)
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_D1, start, end)
    if rates is None or len(rates) < 10:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.set_index("time", inplace=True)
    return df


def get_m1_spread(symbol: str, years: int) -> float:
    """
    Spread weekend moyen estimé depuis les barres M1 du dimanche matin
    (premières 30 minutes après réouverture).
    Retourne le spread en % du prix moyen.
    """
    end   = datetime.utcnow()
    start = end - timedelta(days=365 * years)
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, start, end)
    if rates is None or len(rates) < 100:
        # Fallback: utilise SYMBOL_SPREAD actuel
        info = mt5.symbol_info(symbol)
        if info:
            return info.spread * info.point / info.bid * 100 if info.bid > 0 else 0.0
        return 0.0

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    # Dimanche entre 21:00 et 23:30 UTC (réouverture métaux/forex)
    sunday = df[df["time"].dt.dayofweek == 6]
    sunday_open = sunday[sunday["time"].dt.hour.between(21, 23)]
    if len(sunday_open) < 10:
        # Essaye 20:00-22:00 (heure été)
        sunday_open = sunday[sunday["time"].dt.hour.between(20, 22)]
    if len(sunday_open) < 5:
        info = mt5.symbol_info(symbol)
        if info and info.bid > 0:
            return info.spread * info.point / info.bid * 100
        return 0.0

    avg_price = sunday_open["close"].mean()
    # Spread = high - low sur M1 comme proxy (contient spread + micro-move)
    avg_hl    = (sunday_open["high"] - sunday_open["low"]).mean()
    return (avg_hl / avg_price * 100) if avg_price > 0 else 0.0

# ---------------------------------------------------------------------------
# ANALYSE DES GAPS WEEKEND
# ---------------------------------------------------------------------------

def find_weekend_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Détecte les gaps vendredi close -> dimanche/lundi open.
    Un gap weekend = barre D1 dont le open est ≥ 40h après la barre précédente.
    """
    gaps = []
    df_sorted = df.sort_index()
    times  = df_sorted.index.tolist()
    opens  = df_sorted["open"].tolist()
    closes = df_sorted["close"].tolist()
    highs  = df_sorted["high"].tolist()
    lows   = df_sorted["low"].tolist()

    for i in range(1, len(times)):
        gap_hours = (times[i] - times[i - 1]).total_seconds() / 3600
        if gap_hours < 40:
            continue  # pas un gap weekend

        fri_close  = closes[i - 1]
        sun_open   = opens[i]
        if fri_close <= 0:
            continue

        gap_pct = (sun_open - fri_close) / fri_close * 100.0
        gaps.append({
            "date":       times[i].date(),
            "fri_close":  fri_close,
            "sun_open":   sun_open,
            "gap_pct":    gap_pct,
            "gap_abs":    abs(gap_pct),
            "direction":  "UP" if gap_pct > 0 else "DOWN",
        })

    return pd.DataFrame(gaps)


def lot_value_per_pct(symbol: str) -> float:
    """
    Retourne le profit en $ pour 0.01 lot avec 1% de mouvement.
    Permet de convertir gap% -> gap$.
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.0
    # Profit = (price_change / tick_size) * tick_value * lots
    # Pour 1% de mouvement sur 0.01 lot :
    price     = info.bid if info.bid > 0 else info.ask
    tick_val  = info.trade_tick_value   # $ par tick pour 1 lot
    tick_size = info.trade_tick_size
    if tick_size <= 0 or tick_val <= 0 or price <= 0:
        return 0.0
    move_1pct   = price * 0.01
    ticks_1pct  = move_1pct / tick_size
    return ticks_1pct * tick_val * 0.01   # pour 0.01 lot

# ---------------------------------------------------------------------------
# ANALYSE PRINCIPALE PAR SYMBOLE
# ---------------------------------------------------------------------------

def analyze_symbol(symbol: str, years: int, min_gaps: int) -> dict | None:
    """Retourne un dict de stats ou None si données insuffisantes."""
    # Vérifie que le symbole existe
    if not mt5.symbol_select(symbol, True):
        return None

    df = get_daily_bars(symbol, years)
    if df is None:
        return None

    gaps_df = find_weekend_gaps(df)
    if len(gaps_df) < min_gaps:
        return None

    avg_gap    = gaps_df["gap_abs"].mean()
    median_gap = gaps_df["gap_abs"].median()
    max_gap    = gaps_df["gap_abs"].max()
    std_gap    = gaps_df["gap_abs"].std()

    # Consistance : % de weekends avec gap > 0.25%
    consistency = (gaps_df["gap_abs"] > 0.25).mean() * 100

    # Spread weekend
    spread_pct = get_m1_spread(symbol, min(years, 1))

    # Net edge pour straddle
    net_edge = avg_gap - 2 * spread_pct

    # Profit en $ sur 0.01 lot
    usd_per_pct = lot_value_per_pct(symbol)
    avg_gap_usd = avg_gap * usd_per_pct
    net_edge_usd = net_edge * usd_per_pct

    # Win rate straddle (gap > 2×spread -> trade profitable)
    straddle_wr = (gaps_df["gap_abs"] > 2 * spread_pct).mean() * 100

    # Direction bias (continuation vs fade)
    up_count   = (gaps_df["direction"] == "UP").sum()
    dir_bias   = abs(up_count / len(gaps_df) * 100 - 50)  # 0=neutral, 50=one-sided

    return {
        "symbol":        symbol,
        "n_gaps":        len(gaps_df),
        "avg_gap_pct":   avg_gap,
        "median_gap_pct":median_gap,
        "max_gap_pct":   max_gap,
        "std_gap_pct":   std_gap,
        "consistency":   consistency,
        "spread_pct":    spread_pct,
        "net_edge_pct":  net_edge,
        "avg_gap_usd":   avg_gap_usd,
        "net_edge_usd":  net_edge_usd,
        "straddle_wr":   straddle_wr,
        "dir_bias":      dir_bias,
    }

# ---------------------------------------------------------------------------
# RAPPORT
# ---------------------------------------------------------------------------

def print_report(results: list[dict]) -> None:
    if not results:
        print("\n[!] Aucun résultat — vérifie la connexion MT5 et les symboles disponibles.")
        return

    df = pd.DataFrame(results).sort_values("net_edge_usd", ascending=False)

    print("\n" + "=" * 90)
    print("  CLASSEMENT GAPS WEEKEND — STRATÉGIE STRADDLE (0.01 lot)")
    print("=" * 90)
    print(f"  {'#':<3} {'Symbole':<12} {'N':<5} {'Gap moy%':<10} {'Gap moy$':<10} "
          f"{'Spread%':<9} {'Net$':<9} {'WR%':<7} {'Consist%':<9} {'Biais dir'}")
    print("-" * 90)

    for rank, row in enumerate(df.itertuples(), 1):
        net_flag = "OK" if row.net_edge_usd > 0 else "ERR"
        print(f"  {rank:<3} {row.symbol:<12} {row.n_gaps:<5} "
              f"{row.avg_gap_pct:>7.3f}%  "
              f"${row.avg_gap_usd:>7.2f}   "
              f"{row.spread_pct:>6.3f}%  "
              f"${row.net_edge_usd:>6.2f} {net_flag}  "
              f"{row.straddle_wr:>5.1f}%   "
              f"{row.consistency:>7.1f}%   "
              f"{row.dir_bias:.1f}%")

    # TOP 5
    top5 = df[df["net_edge_usd"] > 0].head(5)
    print("\n" + "=" * 90)
    print("  TOP 5 — MEILLEURS MARCHÉS POUR LE STRADDLE")
    print("=" * 90)
    for rank, row in enumerate(top5.itertuples(), 1):
        print(f"\n  #{rank} {row.symbol}")
        print(f"      Gap moyen     : {row.avg_gap_pct:.3f}%  (${row.avg_gap_usd:.2f} sur 0.01 lot)")
        print(f"      Gap médian    : {row.median_gap_pct:.3f}%")
        print(f"      Gap max       : {row.max_gap_pct:.3f}%")
        print(f"      Spread weekend: {row.spread_pct:.3f}%")
        print(f"      Net edge      : ${row.net_edge_usd:.2f} par trade (après spread)")
        print(f"      WR straddle   : {row.straddle_wr:.1f}% des weekends rentables")
        print(f"      Consistance   : {row.consistency:.1f}% des weekends avec gap > 0.25%")
        print(f"      N gaps        : {row.n_gaps} weekends analysés")

    # Résumé compounding
    print("\n" + "=" * 90)
    print("  SIMULATION STRADDLE 4 SEMAINES — TOP 3 (0.02 lot, $10 loser cap)")
    print("=" * 90)
    for rank, row in enumerate(top5.head(3).itertuples(), 1):
        gap_usd_002 = row.avg_gap_usd * 2   # 0.02 lot = 2× 0.01 lot
        net_per_week = gap_usd_002 - 10.0   # loser cap $10
        capital = 20.0
        print(f"\n  #{rank} {row.symbol}  (gap moy ${gap_usd_002:.2f} sur 0.02 lot)")
        for week in range(1, 5):
            lot = round(max(0.02, (capital - 10) / 500 * 0.02 + 0.02), 2)
            gap_w = row.avg_gap_usd * (lot / 0.01)
            net_w = gap_w - 10.0
            capital += max(0, net_w)
            print(f"    Week {week}: lot={lot:.2f}  gap~${gap_w:.0f}  net~+${net_w:.0f}  -> capital ${capital:.0f}")

    # Export CSV
    out_path = "forex/reports/gap_weekend_ranking.csv"
    try:
        import os
        os.makedirs("forex/reports", exist_ok=True)
        df.to_csv(out_path, index=False, float_format="%.4f")
        print(f"\n  [CSV] Résultats exportés -> {out_path}")
    except Exception as e:
        print(f"\n  [!] Export CSV échoué : {e}")

    print("\n" + "=" * 90)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Weekend gap ranking for straddle strategy")
    parser.add_argument("--years",    type=int, default=3,  help="Années d'historique (défaut: 3)")
    parser.add_argument("--min-gaps", type=int, default=20, help="Min weekends requis (défaut: 20)")
    args = parser.parse_args()

    print(f"\n[START] Analyse gaps weekend — {args.years} ans d'historique, min {args.min_gaps} gaps")
    print(f"        Connexion MT5...")

    if not init_mt5():
        sys.exit(1)

    all_symbols = []
    for category, syms in SYMBOLS.items():
        all_symbols.extend([(s, category) for s in syms])

    results = []
    skipped = []

    for symbol, category in all_symbols:
        print(f"  Analyse {symbol:<12} ({category})...", end=" ", flush=True)
        try:
            res = analyze_symbol(symbol, args.years, args.min_gaps)
            if res:
                res["category"] = category
                results.append(res)
                print(f"OK  {res['n_gaps']} gaps, avg {res['avg_gap_pct']:.3f}%, net ${res['net_edge_usd']:.2f}")
            else:
                skipped.append(symbol)
                print("--  ignoré (données insuffisantes ou symbole indisponible)")
        except Exception as e:
            skipped.append(symbol)
            print(f"ERR  erreur: {e}")

    mt5.shutdown()

    if skipped:
        print(f"\n  Symboles ignorés ({len(skipped)}): {', '.join(skipped)}")

    print_report(results)


if __name__ == "__main__":
    main()
