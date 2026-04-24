"""
scan_gap_ranking_v2.py
======================
Scan all Friday-closing markets available on the connected MT5 broker,
measure weekend gap statistics, deduct spread cost, and rank by net edge.

OUTPUT
------
  Console : ranked table sorted by net_edge (gap% - 2?spread%)
  CSV     : gap_ranking_<broker>_<date>.csv

METRICS PER SYMBOL
------------------
  avg_gap_abs   : mean |gap| in %  (absolute, direction-agnostic)
  std_gap       : standard deviation of gaps (consistency)
  max_gap       : largest single gap seen
  net_edge      : avg_gap_abs - 2?avg_spread% (profit after in+out spread)
  cont_rate     : % of gaps that continue Friday's direction
  sharpe        : avg_gap_abs / std_gap (reward/risk of gap consistency)
  score         : net_edge ? sharpe ? log10(n_gaps)  ? primary ranking key
  n_gaps        : number of weekends analysed (need >= 20)

USAGE
-----
  python scan_gap_ranking_v2.py
  python scan_gap_ranking_v2.py --years 3 --min-gaps 20 --category metals
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

# ??????????????????????????????????????????????????????????????????????????????
# SYMBOL UNIVERSE  (edit / extend freely)
# ??????????????????????????????????????????????????????????????????????????????
SYMBOLS = {
    "metals": [
        "XAUUSD", "XAGUSD", "XAGEUR", "XAUGBP", "XAUJPY",
        "XAUEUR", "XAUGBP", "XAUCHF", "XAUAUD", "XAUSGD",
    ],
    "forex_majors": [
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
        "AUDUSD", "NZDUSD", "USDCAD",
    ],
    "forex_minors": [
        "EURGBP", "EURJPY", "GBPJPY", "EURAUD", "EURCAD",
        "EURCHF", "GBPAUD", "GBPCAD", "AUDJPY", "NZDJPY",
        "CADJPY", "CHFJPY", "AUDCAD", "AUDNZD", "AUDCHF",
    ],
    "forex_exotics": [
        "USDZAR", "USDMXN", "USDSEK", "USDNOK", "USDDKK",
        "USDSGD", "USDHKD", "USDTRY", "EURPLN", "EURTRY",
        "EURZAR", "GBPZAR", "USDHUF", "USDCZK",
    ],
    "indices": [
        "US500", "US30", "NAS100", "UK100", "GER40",
        "FRA40", "ESP35", "JPN225", "AUS200", "HKG33",
        "STOXX50",
    ],
    "commodities": [
        "USOIL", "UKOIL", "NGAS", "COPPER",
        "WHEAT", "CORN", "SOYBEAN", "SUGAR", "COFFEE",
    ],
}

ALL_SYMBOLS = [s for cat in SYMBOLS.values() for s in cat]

# ??????????????????????????????????????????????????????????????????????????????
# CONFIG
# ??????????????????????????????????????????????????????????????????????????????
GAP_MIN_HOURS   = 40      # minimum hours between bars to count as weekend gap
MIN_GAPS        = 20      # discard symbols with fewer weekends than this
SPREAD_WINDOW_H = 2       # hours of M1 data around close/open for spread sampling
TOP_N_DISPLAY   = 40      # rows shown in console table


# ??????????????????????????????????????????????????????????????????????????????
# MT5 HELPERS
# ??????????????????????????????????????????????????????????????????????????????
def connect_mt5() -> bool:
    if not mt5.initialize():
        print(f"[ERROR] MT5 init failed: {mt5.last_error()}")
        return False
    info = mt5.account_info()
    if info:
        print(f"[MT5] Connected -- {info.company}  login={info.login}  "
              f"currency={info.currency}  server={info.server}")
    return True


def resolve_symbol(raw: str) -> str | None:
    """Try the symbol as-is, then with common broker suffixes."""
    for candidate in [raw, raw + "m", raw + ".", raw + ".r", raw + "_i"]:
        if mt5.symbol_info(candidate) is not None:
            mt5.symbol_select(candidate, True)
            return candidate
    return None


def fetch_h1(symbol: str, years: int) -> pd.DataFrame | None:
    utc_to   = datetime.now(timezone.utc)
    utc_from = utc_to - timedelta(days=365 * years + 30)
    bars = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H1,
                                utc_from, utc_to)
    if bars is None or len(bars) < 100:
        return None
    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time").sort_index()
    return df


def fetch_m1_window(symbol: str, center: datetime, hours: int) -> pd.DataFrame | None:
    t_from = center - timedelta(hours=hours)
    t_to   = center + timedelta(hours=hours)
    bars = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, t_from, t_to)
    if bars is None or len(bars) == 0:
        return None
    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df["spread_pts"] = df["spread"]
    return df


# ??????????????????????????????????????????????????????????????????????????????
# CORE ANALYSIS
# ??????????????????????????????????????????????????????????????????????????????
def analyse_symbol(symbol: str, years: int) -> dict | None:
    resolved = resolve_symbol(symbol)
    if resolved is None:
        return None

    info = mt5.symbol_info(resolved)
    if info is None:
        return None
    point  = info.point
    digits = info.digits

    df = fetch_h1(resolved, years)
    if df is None:
        return None

    # ?? detect weekend gaps (gap between consecutive H1 bars >= GAP_MIN_HOURS) ??
    times = df.index.to_numpy()          # numpy datetime64[ns, UTC]
    gaps  = []

    for i in range(1, len(df)):
        dt_prev = pd.Timestamp(times[i - 1])
        dt_curr = pd.Timestamp(times[i])
        gap_h   = (dt_curr - dt_prev).total_seconds() / 3600.0

        if gap_h < GAP_MIN_HOURS:
            continue

        close_price = float(df.iloc[i - 1]["close"])
        open_price  = float(df.iloc[i]["open"])
        if close_price <= 0:
            continue

        gap_pct = (open_price - close_price) / close_price * 100.0

        # Friday direction: compare close to open of that Friday session (H1 bar 20h before)
        fri_idx = i - 1
        lookback = 20
        ref_idx  = max(0, fri_idx - lookback)
        fri_open = float(df.iloc[ref_idx]["open"])
        friday_dir = 1 if close_price > fri_open else (-1 if close_price < fri_open else 0)
        continuation = 1 if (friday_dir * gap_pct > 0) else 0

        gaps.append({
            "close_time"  : dt_prev,
            "open_time"   : dt_curr,
            "close_price" : close_price,
            "open_price"  : open_price,
            "gap_pct"     : gap_pct,
            "gap_abs_pct" : abs(gap_pct),
            "continuation": continuation,
            "friday_dir"  : friday_dir,
        })

    if len(gaps) < MIN_GAPS:
        return None

    gdf = pd.DataFrame(gaps)

    # ?? spread sampling (M1 around close + open for a sample of weekends) ??
    spread_samples = []
    sample_indices = list(range(0, len(gdf), max(1, len(gdf) // 20)))[:20]  # up to 20 samples
    for idx in sample_indices:
        row = gdf.iloc[idx]
        close_ts = row["close_time"].to_pydatetime().replace(tzinfo=timezone.utc)
        open_ts  = row["open_time"].to_pydatetime().replace(tzinfo=timezone.utc)
        cp = row["close_price"]

        m1_close = fetch_m1_window(resolved, close_ts, SPREAD_WINDOW_H)
        m1_open  = fetch_m1_window(resolved, open_ts,  SPREAD_WINDOW_H)

        if m1_close is not None and len(m1_close) > 0:
            sp_pts = m1_close["spread_pts"].mean()
            spread_samples.append(sp_pts * point / cp * 100.0)
        if m1_open is not None and len(m1_open) > 0:
            sp_pts = m1_open["spread_pts"].mean()
            spread_samples.append(sp_pts * point / cp * 100.0)

    avg_spread_pct = float(np.mean(spread_samples)) if spread_samples else np.nan

    # ?? aggregate stats ??
    avg_gap_abs  = gdf["gap_abs_pct"].mean()
    std_gap      = gdf["gap_abs_pct"].std()
    max_gap      = gdf["gap_abs_pct"].max()
    cont_rate    = gdf["continuation"].mean() * 100.0
    n_gaps       = len(gdf)

    # sharpe = reward / consistency  (higher = more consistent large gaps)
    sharpe = avg_gap_abs / std_gap if std_gap > 0 else 0.0

    # net_edge after in+out spread (NaN if spread not available)
    if not np.isnan(avg_spread_pct):
        net_edge = avg_gap_abs - 2.0 * avg_spread_pct
    else:
        net_edge = avg_gap_abs  # optimistic fallback -- flag with *

    # composite score: net_edge ? sharpe ? log10(n_gaps)
    score = net_edge * sharpe * np.log10(max(n_gaps, 2)) if net_edge > 0 else 0.0

    # gap distribution percentiles
    p25 = gdf["gap_abs_pct"].quantile(0.25)
    p50 = gdf["gap_abs_pct"].quantile(0.50)
    p75 = gdf["gap_abs_pct"].quantile(0.75)
    p90 = gdf["gap_abs_pct"].quantile(0.90)
    pct_above_1 = (gdf["gap_abs_pct"] > 1.0).mean() * 100.0

    # category
    cat = "other"
    for c, syms in SYMBOLS.items():
        if symbol in syms:
            cat = c
            break

    return {
        "symbol"        : resolved,
        "base_symbol"   : symbol,
        "category"      : cat,
        "n_gaps"        : n_gaps,
        "avg_gap_abs"   : round(avg_gap_abs,  4),
        "std_gap"       : round(std_gap,       4),
        "max_gap"       : round(max_gap,       4),
        "p25_gap"       : round(p25,           4),
        "p50_gap"       : round(p50,           4),
        "p75_gap"       : round(p75,           4),
        "p90_gap"       : round(p90,           4),
        "pct_above_1pct": round(pct_above_1,   1),
        "cont_rate"     : round(cont_rate,     1),
        "avg_spread_pct": round(avg_spread_pct, 4) if not np.isnan(avg_spread_pct) else None,
        "net_edge"      : round(net_edge,      4),
        "sharpe"        : round(sharpe,        3),
        "score"         : round(score,         4),
        "spread_flag"   : "*" if np.isnan(avg_spread_pct) else "",
    }


# ??????????????????????????????????????????????????????????????????????????????
# DISPLAY
# ??????????????????????????????????????????????????????????????????????????????
def print_table(df: pd.DataFrame, top_n: int):
    top = df.head(top_n).copy()
    print()
    print("=" * 110)
    print(f"  WEEKEND GAP RANKING  --  {len(df)} symbols analysed, top {min(top_n, len(df))} shown")
    print("=" * 110)
    hdr = (f"{'#':>3}  {'SYMBOL':<12} {'CAT':<14} {'n':>5}  "
           f"{'avg|gap|':>8}  {'std':>6}  {'max':>6}  "
           f"{'p50':>5}  {'p90':>5}  {'>1%':>5}  "
           f"{'spread':>7}  {'net_edge':>8}  {'sharpe':>6}  {'score':>7}  {'cont%':>6}")
    print(hdr)
    print("-" * 110)

    for rank, (_, row) in enumerate(top.iterrows(), 1):
        spread_str = (f"{row['avg_spread_pct']:.3f}%" if row["avg_spread_pct"] is not None
                      else "  N/A*")
        net_str = f"{row['net_edge']:+.3f}%"
        flag = row.get("spread_flag", "")
        print(
            f"{rank:>3}  {str(row['symbol']):<12} {row['category']:<14} {row['n_gaps']:>5}  "
            f"{row['avg_gap_abs']:>7.3f}%  {row['std_gap']:>5.3f}  {row['max_gap']:>5.2f}  "
            f"{row['p50_gap']:>4.3f}  {row['p90_gap']:>4.3f}  {row['pct_above_1pct']:>4.0f}%  "
            f"{spread_str:>7}  {net_str:>8}  {row['sharpe']:>6.3f}  "
            f"{row['score']:>7.4f}  {row['cont_rate']:>5.1f}%{flag}"
        )

    print()
    print("  LEGEND")
    print("  avg|gap|  : mean absolute gap (Friday close -> Sunday open) as %")
    print("  p50/p90   : median / 90th percentile gap")
    print("  >1%       : % of weekends where gap exceeded 1%")
    print("  spread    : avg spread at close+open as % of price (* = no M1 data)")
    print("  net_edge  : avg|gap| - 2?spread  (positive = exploitable after cost)")
    print("  sharpe    : avg_gap / std  (consistency of large gaps)")
    print("  score     : net_edge ? sharpe ? log10(n)  ? PRIMARY RANKING KEY")
    print("  cont%     : % of gaps continuing Friday's direction (50% = random)")
    print("=" * 110)


def print_category_summary(df: pd.DataFrame):
    print()
    print("  CATEGORY SUMMARY")
    print("  " + "-" * 60)
    grp = (df.groupby("category")
             .agg(count=("symbol","count"),
                  avg_score=("score","mean"),
                  avg_net_edge=("net_edge","mean"),
                  best_symbol=("symbol","first"))
             .sort_values("avg_score", ascending=False))
    for cat, row in grp.iterrows():
        print(f"  {cat:<16} n={row['count']:>2}  "
              f"avg_score={row['avg_score']:.3f}  "
              f"avg_net_edge={row['avg_net_edge']:+.3f}%  "
              f"best={row['best_symbol']}")
    print()


# ??????????????????????????????????????????????????????????????????????????????
# MAIN
# ??????????????????????????????????????????????????????????????????????????????
def main():
    parser = argparse.ArgumentParser(description="Weekend gap ranking scanner")
    parser.add_argument("--years",    type=int,   default=4,
                        help="Years of history to analyse (default 4)")
    parser.add_argument("--min-gaps", type=int,   default=MIN_GAPS,
                        help=f"Minimum weekends required (default {MIN_GAPS})")
    parser.add_argument("--category", type=str,   default="all",
                        help="Filter: all / metals / forex_majors / forex_minors / "
                             "forex_exotics / indices / commodities")
    parser.add_argument("--top",      type=int,   default=TOP_N_DISPLAY,
                        help=f"Rows to display (default {TOP_N_DISPLAY})")
    parser.add_argument("--no-save",  action="store_true",
                        help="Do not save CSV")
    args = parser.parse_args()

    if not connect_mt5():
        sys.exit(1)

    # select symbol universe
    if args.category == "all":
        universe = ALL_SYMBOLS
    elif args.category in SYMBOLS:
        universe = SYMBOLS[args.category]
    else:
        print(f"[ERROR] Unknown category '{args.category}'. "
              f"Choose from: {list(SYMBOLS.keys())}")
        sys.exit(1)

    # remove duplicates while preserving order
    seen = set(); universe = [s for s in universe if not (s in seen or seen.add(s))]

    print(f"\n[SCAN] {len(universe)} symbols  |  {args.years}y history  |  "
          f"min {args.min_gaps} weekends\n")

    results = []
    for i, sym in enumerate(universe):
        print(f"  [{i+1:>3}/{len(universe)}]  {sym:<14}", end="", flush=True)
        res = analyse_symbol(sym, args.years)
        if res is None:
            print("  -- skipped (no data / insufficient gaps)")
        else:
            results.append(res)
            print(f"  n={res['n_gaps']:>3}  avg|gap|={res['avg_gap_abs']:.3f}%  "
                  f"net_edge={res['net_edge']:+.3f}%  score={res['score']:.3f}")

    mt5.shutdown()

    if not results:
        print("\n[WARN] No symbols passed the minimum gap filter.")
        sys.exit(0)

    df = (pd.DataFrame(results)
            .sort_values("score", ascending=False)
            .reset_index(drop=True))

    print_table(df, args.top)
    print_category_summary(df)

    if not args.no_save:
        broker_tag = "exness"  # change if needed
        date_tag   = datetime.now().strftime("%Y%m%d")
        out_path   = Path(f"gap_ranking_{broker_tag}_{date_tag}.csv")
        df.to_csv(out_path, index=False)
        print(f"  Saved -> {out_path.resolve()}\n")


if __name__ == "__main__":
    main()
