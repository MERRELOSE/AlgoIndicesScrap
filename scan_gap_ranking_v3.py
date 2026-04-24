"""
scan_gap_ranking_v3.py
=======================
Weekend gap scanner — merged best of v1+v2 with reliable spread measurement.

GAP DETECTION (reliable):
  - H1 bars: consecutive bars with >= 40h gap = weekend gap
  - Day-of-week check: close must be Fri(4)/Sat(5), open must be Sun(6)/Mon(0)
  - Anomaly filter: |gap| > 20% excluded (data artifact), < 0.001% excluded (noise)
  - No hardcoded session hours — the data defines when the market was closed

SPREAD MEASUREMENT (correct, asymmetric):
  - Sunday open spread  : MAX spread over first 5 M1 bars after reopen (true peak)
  - Friday close spread : MEAN spread over last 15 M1 bars before close (normal hours)
  - Round-trip cost     : sun_open_spread + fri_close_spread  (not 2 x average)
  - Up to 30 sampled weekends per symbol, evenly spaced across full history

METRICS:
  avg|gap|     mean absolute gap % (Friday close -> Sunday open)
  std          standard deviation of gaps
  p50 / p90   median and 90th percentile gap
  consist%     % of weekends where |gap| > 0.25%
  >1%          % of weekends where |gap| > 1%
  sun_sp       peak spread at Sunday reopen
  fri_sp       spread at Friday close
  rt_sp        round-trip spread (entry + exit cost)
  net_edge     avg|gap| - rt_spread (positive = exploitable after cost)
  wr%          % of weekends where |gap| > rt_spread (trade was profitable)
  sharpe       avg|gap| / std (consistency of large gaps)
  score        net_edge x sharpe x log10(n)  <- PRIMARY RANKING KEY
  cont%        % of gaps continuing Friday's direction (50% = random)
  bias         |50% - up%| (0 = random, 50 = always gaps in one direction)

USAGE:
  python scan_gap_ranking_v3.py
  python scan_gap_ranking_v3.py --years 4 --min-gaps 20 --category metals
  python scan_gap_ranking_v3.py --no-save
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────
# SYMBOL UNIVERSE
# ─────────────────────────────────────────────────────────────
SYMBOLS: dict[str, list[str]] = {
    "metals": [
        "XAUUSD", "XAGUSD", "XAGEUR", "XAUEUR",
        "XAUGBP", "XAUJPY", "XAUCHF", "XAUAUD",
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
        "FRA40", "ESP35", "JPN225", "AUS200", "HKG33", "STOXX50",
    ],
    "commodities": [
        "USOIL", "UKOIL", "NGAS", "COPPER",
        "WHEAT", "CORN", "SOYBEAN", "SUGAR", "COFFEE",
    ],
}

# dedup while preserving insertion order
_seen_s: set[str] = set()
ALL_SYMBOLS: list[str] = []
for _syms in SYMBOLS.values():
    for _s in _syms:
        if _s not in _seen_s:
            ALL_SYMBOLS.append(_s)
            _seen_s.add(_s)

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
GAP_MIN_HOURS     = 40      # min hours between H1 bars to qualify as weekend gap
GAP_MAX_PCT       = 20.0    # gaps above this % are data artifacts → excluded
GAP_NOISE_PCT     = 0.001   # gaps below this % are noise → excluded
MIN_GAPS          = 20      # discard symbols with fewer qualified weekends
SPREAD_N_SAMPLES  = 30      # max weekends sampled for spread measurement
SPREAD_PEAK_BARS  = 5       # number of first M1 bars used for Sunday peak spread
TOP_N_DISPLAY     = 40      # rows in console table


# ─────────────────────────────────────────────────────────────
# MT5 HELPERS
# ─────────────────────────────────────────────────────────────
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
    """Try the symbol as-is, then common broker suffixes."""
    for candidate in [raw, raw + "m", raw + ".", raw + ".r", raw + "_i"]:
        if mt5.symbol_info(candidate) is not None:
            mt5.symbol_select(candidate, True)
            return candidate
    return None


def fetch_h1(symbol: str, years: int) -> pd.DataFrame | None:
    utc_to   = datetime.now(timezone.utc)
    utc_from = utc_to - timedelta(days=365 * years + 30)
    bars = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H1, utc_from, utc_to)
    if bars is None or len(bars) < 100:
        return None
    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df.set_index("time").sort_index()


def fetch_m1_range(symbol: str, t_from: datetime, t_to: datetime) -> pd.DataFrame | None:
    bars = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, t_from, t_to)
    if bars is None or len(bars) == 0:
        return None
    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df.sort_values("time").reset_index(drop=True)


def lot_value_per_pct(symbol: str) -> float:
    """Dollar profit for 0.01 lot with 1% price move."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.0
    price     = info.bid if info.bid > 0 else info.ask
    tick_val  = info.trade_tick_value
    tick_size = info.trade_tick_size
    if tick_size <= 0 or tick_val <= 0 or price <= 0:
        return 0.0
    ticks_1pct = (price * 0.01) / tick_size
    return ticks_1pct * tick_val * 0.01


# ─────────────────────────────────────────────────────────────
# CORE ANALYSIS
# ─────────────────────────────────────────────────────────────
def analyse_symbol(symbol: str, years: int) -> dict | None:
    resolved = resolve_symbol(symbol)
    if resolved is None:
        return None

    info = mt5.symbol_info(resolved)
    if info is None:
        return None
    point = info.point

    df = fetch_h1(resolved, years)
    if df is None:
        return None

    times = df.index.to_numpy()
    gaps: list[dict] = []

    for i in range(1, len(df)):
        dt_prev = pd.Timestamp(times[i - 1])
        dt_curr = pd.Timestamp(times[i])
        gap_h   = (dt_curr - dt_prev).total_seconds() / 3600.0

        if gap_h < GAP_MIN_HOURS:
            continue

        # ── Weekend day-of-week verification ──────────────────────────────
        # close_time should be Friday (4) or Saturday (5) — some brokers close earlier
        # open_time  should be Sunday (6) or Monday (0)   — some brokers open late
        close_dow = dt_prev.dayofweek
        open_dow  = dt_curr.dayofweek
        if close_dow not in (4, 5) or open_dow not in (6, 0):
            continue  # holiday / maintenance break, not a real weekend gap

        close_price = float(df.iloc[i - 1]["close"])
        open_price  = float(df.iloc[i]["open"])
        if close_price <= 0:
            continue

        gap_pct = (open_price - close_price) / close_price * 100.0
        gap_abs = abs(gap_pct)

        # ── Anomaly & noise filters ────────────────────────────────────────
        if gap_abs > GAP_MAX_PCT or gap_abs < GAP_NOISE_PCT:
            continue

        # Friday trend direction (compare Friday close to ~20h earlier)
        ref_idx    = max(0, i - 1 - 20)
        fri_open   = float(df.iloc[ref_idx]["open"])
        friday_dir = 1 if close_price > fri_open else (-1 if close_price < fri_open else 0)
        cont       = 1 if friday_dir * gap_pct > 0 else 0

        gaps.append({
            "close_time"  : dt_prev,
            "open_time"   : dt_curr,
            "close_price" : close_price,
            "open_price"  : open_price,
            "gap_pct"     : gap_pct,
            "gap_abs_pct" : gap_abs,
            "continuation": cont,
            "friday_dir"  : friday_dir,
        })

    if len(gaps) < MIN_GAPS:
        return None

    gdf = pd.DataFrame(gaps)

    # ── Spread measurement ─────────────────────────────────────────────────
    # Sample evenly across all weekends (up to SPREAD_N_SAMPLES)
    n      = len(gdf)
    step   = max(1, n // SPREAD_N_SAMPLES)
    idxs   = list(range(0, n, step))[:SPREAD_N_SAMPLES]

    sun_spread_list: list[float] = []  # peak spread at Sunday reopen
    fri_spread_list: list[float] = []  # normal spread at Friday close

    for idx in idxs:
        row      = gdf.iloc[idx]
        close_ts = row["close_time"].to_pydatetime().replace(tzinfo=timezone.utc)
        open_ts  = row["open_time"].to_pydatetime().replace(tzinfo=timezone.utc)
        cp       = row["close_price"]
        op       = row["open_price"]

        # Sunday open: fetch first 20 M1 bars starting at reopen time
        # Take the MAX spread over first SPREAD_PEAK_BARS bars = worst-case peak
        m1_sun = fetch_m1_range(resolved, open_ts - timedelta(minutes=2),
                                           open_ts + timedelta(minutes=20))
        if m1_sun is not None and len(m1_sun) > 0:
            # filter to bars AT or AFTER open_ts to avoid pre-open noise
            m1_sun = m1_sun[m1_sun["time"] >= (open_ts - timedelta(minutes=1))]
            if len(m1_sun) > 0:
                peak_bars = m1_sun.head(SPREAD_PEAK_BARS)
                peak_sp   = peak_bars["spread"].max()   # worst (highest) spread
                if peak_sp > 0:
                    sun_spread_list.append(peak_sp * point / op * 100.0)

        # Friday close: fetch last 15 M1 bars before close
        # Take the MEAN — spread is normal during trading hours
        m1_fri = fetch_m1_range(resolved, close_ts - timedelta(minutes=15), close_ts)
        if m1_fri is not None and len(m1_fri) > 0:
            avg_sp = m1_fri["spread"].mean()
            if avg_sp > 0:
                fri_spread_list.append(avg_sp * point / cp * 100.0)

    sun_sp_avg = float(np.mean(sun_spread_list)) if sun_spread_list else np.nan
    fri_sp_avg = float(np.mean(fri_spread_list)) if fri_spread_list else np.nan

    # Round-trip spread = entry (Friday) + exit (Sunday)
    if not np.isnan(sun_sp_avg) and not np.isnan(fri_sp_avg):
        rt_spread = sun_sp_avg + fri_sp_avg
    elif not np.isnan(sun_sp_avg):
        rt_spread = sun_sp_avg * 2.0   # conservative: assume equal both sides
    elif not np.isnan(fri_sp_avg):
        rt_spread = fri_sp_avg * 2.0
    else:
        rt_spread = np.nan

    spread_flag = "*" if np.isnan(rt_spread) else ""

    # ── Aggregate gap statistics ───────────────────────────────────────────
    avg_gap  = gdf["gap_abs_pct"].mean()
    std_gap  = gdf["gap_abs_pct"].std()
    max_gap  = gdf["gap_abs_pct"].max()
    n_gaps   = len(gdf)

    p25 = gdf["gap_abs_pct"].quantile(0.25)
    p50 = gdf["gap_abs_pct"].quantile(0.50)
    p75 = gdf["gap_abs_pct"].quantile(0.75)
    p90 = gdf["gap_abs_pct"].quantile(0.90)

    cont_rate   = gdf["continuation"].mean() * 100.0
    consistency = (gdf["gap_abs_pct"] > 0.25).mean() * 100.0
    up_pct      = (gdf["gap_pct"] > 0).mean() * 100.0
    dir_bias    = abs(up_pct - 50.0)
    pct_above1  = (gdf["gap_abs_pct"] > 1.0).mean() * 100.0

    sharpe = avg_gap / std_gap if std_gap > 0 else 0.0

    if not np.isnan(rt_spread):
        net_edge   = avg_gap - rt_spread
        wr_pct     = (gdf["gap_abs_pct"] > rt_spread).mean() * 100.0
    else:
        net_edge   = avg_gap   # optimistic fallback
        wr_pct     = np.nan

    score = net_edge * sharpe * np.log10(max(n_gaps, 2)) if net_edge > 0 else 0.0

    usd_per_pct = lot_value_per_pct(resolved)
    net_edge_usd = net_edge * usd_per_pct if usd_per_pct > 0 else np.nan

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
        "avg_gap_abs"   : round(avg_gap,   4),
        "std_gap"       : round(std_gap,   4),
        "max_gap"       : round(max_gap,   4),
        "p25_gap"       : round(p25,       4),
        "p50_gap"       : round(p50,       4),
        "p75_gap"       : round(p75,       4),
        "p90_gap"       : round(p90,       4),
        "pct_above_1pct": round(pct_above1, 1),
        "consistency"   : round(consistency, 1),
        "cont_rate"     : round(cont_rate,   1),
        "dir_bias"      : round(dir_bias,    1),
        "up_pct"        : round(up_pct,      1),
        "sun_spread_pct": (round(sun_sp_avg, 5) if not np.isnan(sun_sp_avg) else None),
        "fri_spread_pct": (round(fri_sp_avg, 5) if not np.isnan(fri_sp_avg) else None),
        "rt_spread_pct" : (round(rt_spread,  4) if not np.isnan(rt_spread)  else None),
        "net_edge_pct"  : round(net_edge,    4),
        "net_edge_usd"  : (round(net_edge_usd, 4) if not np.isnan(net_edge_usd) else None),
        "straddle_wr"   : (round(wr_pct, 1) if not np.isnan(wr_pct) else None),
        "sharpe"        : round(sharpe,   3),
        "score"         : round(score,    4),
        "spread_flag"   : spread_flag,
    }


# ─────────────────────────────────────────────────────────────
# DISPLAY
# ─────────────────────────────────────────────────────────────
def fmt_pct(v, decimals=3) -> str:
    return f"{v:.{decimals}f}%" if v is not None else "  N/A"


def print_table(df: pd.DataFrame, top_n: int) -> None:
    top = df.head(top_n).copy()
    W = 130
    print()
    print("=" * W)
    print(f"  WEEKEND GAP RANKING v3  --  {len(df)} symbols analysed, top {min(top_n, len(df))} shown")
    print("=" * W)
    hdr = (
        f"{'#':>3}  {'SYMBOL':<10} {'CAT':<14} {'n':>5}  "
        f"{'avg|gap|':>8}  {'p50':>5}  {'p90':>5}  {'cons%':>5}  {'>1%':>4}  "
        f"{'sun_sp':>7}  {'fri_sp':>7}  {'rt_sp':>7}  "
        f"{'net_edge':>8}  {'WR%':>5}  {'sharpe':>6}  {'score':>7}  "
        f"{'cont%':>5}  {'bias':>4}"
    )
    print(hdr)
    print("-" * W)

    for rank, (_, row) in enumerate(top.iterrows(), 1):
        flag = row.get("spread_flag", "")
        print(
            f"{rank:>3}  {str(row['symbol']):<10} {row['category']:<14} {row['n_gaps']:>5}  "
            f"{row['avg_gap_abs']:>7.3f}%  {row['p50_gap']:>4.3f}  {row['p90_gap']:>4.3f}  "
            f"{row['consistency']:>4.0f}%  {row['pct_above_1pct']:>3.0f}%  "
            f"{fmt_pct(row['sun_spread_pct'], 4):>8}  "
            f"{fmt_pct(row['fri_spread_pct'], 4):>8}  "
            f"{fmt_pct(row['rt_spread_pct'],  4):>8}  "
            f"{row['net_edge_pct']:>+7.3f}%  "
            f"{(str(round(row['straddle_wr'])) + '%') if (row['straddle_wr'] is not None and not pd.isna(row['straddle_wr'])) else 'N/A':>5}  "
            f"{row['sharpe']:>6.3f}  {row['score']:>7.4f}  "
            f"{row['cont_rate']:>4.1f}%  {row['dir_bias']:>3.1f}{flag}"
        )

    print()
    print("  LEGEND")
    print("  avg|gap|  : mean absolute gap (Friday close -> Sunday open) as %")
    print("  p50/p90   : median / 90th percentile of |gap|")
    print("  cons%     : % weekends where |gap| > 0.25%  (reliable occurrence)")
    print("  >1%       : % weekends where |gap| > 1%")
    print("  sun_sp    : peak spread at Sunday reopen (max of first 5 M1 bars)")
    print("  fri_sp    : spread at Friday close (avg last 15 M1 bars, normal hours)")
    print("  rt_sp     : round-trip spread = sun_sp + fri_sp")
    print("  net_edge  : avg|gap| - rt_spread  (positive = profitable after cost)")
    print("  WR%       : % weekends where |gap| > rt_spread  (trade was profitable)")
    print("  sharpe    : avg|gap| / std  (consistency of large gaps)")
    print("  score     : net_edge x sharpe x log10(n)  <- PRIMARY RANKING KEY")
    print("  cont%     : % gaps continuing Friday direction  (50% = random)")
    print("  bias      : |50% - up%|  (0 = balanced, 45 = almost always same direction)")
    print("  *         : spread could not be measured (no M1 data)")
    print("=" * W)


def print_category_summary(df: pd.DataFrame) -> None:
    print()
    print("  CATEGORY SUMMARY")
    print("  " + "-" * 70)
    grp = (
        df.groupby("category")
          .agg(count=("symbol", "count"),
               avg_score=("score", "mean"),
               avg_net_edge=("net_edge_pct", "mean"),
               best_symbol=("symbol", "first"))
          .sort_values("avg_score", ascending=False)
    )
    for cat, row in grp.iterrows():
        print(f"  {cat:<16} n={row['count']:>2}  "
              f"avg_score={row['avg_score']:.3f}  "
              f"avg_net_edge={row['avg_net_edge']:+.3f}%  "
              f"best={row['best_symbol']}")


def print_top5_detail(df: pd.DataFrame) -> None:
    top5 = df[df["net_edge_pct"] > 0].head(5)
    print()
    print("=" * 80)
    print("  TOP 5  --  BEST WEEKEND GAP CANDIDATES")
    print("=" * 80)
    for rank, (_, row) in enumerate(top5.iterrows(), 1):
        usd_str = (f"  (~${row['net_edge_usd']:.2f} per 0.01 lot)"
                   if row["net_edge_usd"] is not None else "")
        print(f"""
  #{rank}  {row['symbol']}  ({row['category']})
      Gaps analysed  : {row['n_gaps']} weekends  |  consistent: {row['consistency']:.0f}% occur above 0.25%
      Avg gap        : {row['avg_gap_abs']:.3f}%   p50={row['p50_gap']:.3f}%  p90={row['p90_gap']:.3f}%  max={row['max_gap']:.2f}%
      Spread (Sun)   : {fmt_pct(row['sun_spread_pct'], 4)}  (Fri): {fmt_pct(row['fri_spread_pct'], 4)}  RT: {fmt_pct(row['rt_spread_pct'], 4)}
      Net edge       : {row['net_edge_pct']:+.3f}%{usd_str}
      Win rate       : {(str(round(row['straddle_wr'])) + '%') if (row['straddle_wr'] is not None and not pd.isna(row['straddle_wr'])) else 'N/A'} of weekends gap > spread
      Sharpe / Score : {row['sharpe']:.3f} / {row['score']:.4f}
      Direction      : {row['cont_rate']:.0f}% continuation  |  {row['up_pct']:.0f}% gap upward  |  bias={row['dir_bias']:.1f}""")
    print()


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Weekend gap ranking scanner v3")
    parser.add_argument("--years",    type=int, default=4,
                        help="Years of history to analyse (default 4)")
    parser.add_argument("--min-gaps", type=int, default=MIN_GAPS,
                        help=f"Minimum weekends required (default {MIN_GAPS})")
    parser.add_argument("--category", type=str, default="all",
                        help="Filter: all / metals / forex_majors / forex_minors / "
                             "forex_exotics / indices / commodities")
    parser.add_argument("--top",      type=int, default=TOP_N_DISPLAY,
                        help=f"Rows to display (default {TOP_N_DISPLAY})")
    parser.add_argument("--no-save",  action="store_true",
                        help="Do not save CSV")
    args = parser.parse_args()

    if not connect_mt5():
        sys.exit(1)

    if args.category == "all":
        universe = ALL_SYMBOLS
    elif args.category in SYMBOLS:
        universe = SYMBOLS[args.category]
    else:
        print(f"[ERROR] Unknown category '{args.category}'. "
              f"Choose from: {list(SYMBOLS.keys())}")
        sys.exit(1)

    # dedup preserving order
    _s: set[str] = set()
    universe = [x for x in universe if not (_s.add(x) or x in _s - {x})]

    print(f"\n[SCAN] {len(universe)} symbols  |  {args.years}y history  |  "
          f"min {args.min_gaps} weekends\n"
          f"       Spread: first {SPREAD_PEAK_BARS} M1 bars (Sunday peak) + last 15 M1 bars (Friday normal)\n")

    results: list[dict] = []
    for i, sym in enumerate(universe):
        print(f"  [{i + 1:>3}/{len(universe)}]  {sym:<14}", end="", flush=True)
        res = analyse_symbol(sym, args.years)
        if res is None:
            print("  -- skipped (no data / insufficient gaps)")
        else:
            results.append(res)
            flag = res["spread_flag"]
            print(
                f"  n={res['n_gaps']:>3}  "
                f"avg|gap|={res['avg_gap_abs']:.3f}%  "
                f"rt_sp={fmt_pct(res['rt_spread_pct'], 4).strip():>8}  "
                f"net={res['net_edge_pct']:+.3f}%  "
                f"score={res['score']:.3f}{flag}"
            )

    mt5.shutdown()

    if not results:
        print("\n[WARN] No symbols passed the minimum gap filter.")
        sys.exit(0)

    df = (
        pd.DataFrame(results)
          .sort_values("score", ascending=False)
          .reset_index(drop=True)
    )

    print_table(df, args.top)
    print_category_summary(df)
    print_top5_detail(df)

    if not args.no_save:
        broker_tag = "deriv"
        date_tag   = datetime.now().strftime("%Y%m%d")
        out_path   = Path(f"gap_ranking_v3_{broker_tag}_{date_tag}.csv")
        df.to_csv(out_path, index=False)
        print(f"  Saved -> {out_path.resolve()}\n")


if __name__ == "__main__":
    main()
