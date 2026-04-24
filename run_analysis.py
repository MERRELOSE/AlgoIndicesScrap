#!/usr/bin/env python3
"""
Pipeline complet : Extraction + Analyse Statistique
Objectif : Determiner s'il y a un signal exploitable dans les indices synthetiques Deriv
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import websockets
from loguru import logger

# ============================================================
# PARTIE 1 : EXTRACTION AVEC PAGINATION CORRECTE
# ============================================================

SYMBOL_MAP = {
    'Crash 500 Index': 'CRASH500',
    'Crash 1000 Index': 'CRASH1000',
    'Boom 500 Index': 'BOOM500',
    'Boom 1000 Index': 'BOOM1000',
    'Volatility 10 Index': 'R_10',
    'Volatility 25 Index': 'R_25',
    'Volatility 50 Index': 'R_50',
    'Volatility 75 Index': 'R_75',
    'Volatility 100 Index': 'R_100',
    'Step Index': 'stpRNG',
}

GRANULARITY = {
    'M1': 60, 'M5': 300, 'M15': 900,
    'H1': 3600, 'H4': 14400, 'D1': 86400,
}

WS_URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"


async def fetch_candles(ws, symbol: str, granularity: int, count: int, end_epoch: int = None):
    """Fetch candles with proper pagination using end timestamp"""
    request = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": min(count, 5000),
        "end": end_epoch if end_epoch else "latest",
        "granularity": granularity,
        "start": 1,
        "style": "candles"
    }
    await ws.send(json.dumps(request))
    response = await ws.recv()
    data = json.loads(response)

    if 'error' in data:
        logger.error(f"API Error: {data['error']['message']}")
        return []

    return data.get('candles', [])


async def extract_symbol(symbol: str, timeframe: str, target_candles: int = 10000):
    """Extract data with proper backward pagination"""
    deriv_symbol = SYMBOL_MAP.get(symbol, symbol)
    gran = GRANULARITY[timeframe]

    logger.info(f"Extracting {symbol} ({deriv_symbol}) {timeframe} - target: {target_candles} candles")

    all_candles = []
    end_epoch = None  # Start from latest
    batch_num = 0

    async with websockets.connect(WS_URL) as ws:
        while len(all_candles) < target_candles:
            batch_num += 1
            remaining = target_candles - len(all_candles)
            batch_size = min(remaining, 5000)

            candles = await fetch_candles(ws, deriv_symbol, gran, batch_size, end_epoch)

            if not candles:
                logger.warning(f"  Batch {batch_num}: No data returned, stopping")
                break

            # Set end_epoch for next batch = oldest candle of this batch - 1 second
            end_epoch = candles[0]['epoch'] - 1

            # Prepend (older data goes first)
            all_candles = candles + all_candles

            # Remove duplicates by epoch
            seen = set()
            unique = []
            for c in all_candles:
                if c['epoch'] not in seen:
                    seen.add(c['epoch'])
                    unique.append(c)
            all_candles = sorted(unique, key=lambda x: x['epoch'])

            prev_total = len(all_candles) - len(candles)  # approximate
            new_unique = len(all_candles)
            gained = new_unique - prev_total if batch_num > 1 else len(candles)
            logger.info(f"  Batch {batch_num}: +{gained} new candles | Total: {len(all_candles)}")

            if len(candles) < 100:
                logger.info("  Reached end of available history")
                break

            # Stop if we're not gaining new candles (API history limit reached)
            if batch_num > 1 and gained < 50:
                logger.info(f"  History limit reached (only {gained} new candles), stopping")
                break

            # Rate limiting
            await asyncio.sleep(1.5)

    if not all_candles:
        return None

    # Convert to DataFrame
    df = pd.DataFrame(all_candles)
    df.rename(columns={
        'epoch': 'timestamp',
        'open': 'Open', 'high': 'High',
        'low': 'Low', 'close': 'Close'
    }, inplace=True)

    # Convert types
    for col in ['Open', 'High', 'Low', 'Close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
    df.set_index('datetime', inplace=True)
    df.drop('timestamp', axis=1, inplace=True)
    df = df.sort_index()

    days_covered = (df.index[-1] - df.index[0]).days
    logger.info(f"  DONE: {len(df)} candles over {days_covered} days")
    logger.info(f"  Range: {df.index[0]} -> {df.index[-1]}")

    return df


# ============================================================
# PARTIE 2 : ANALYSE STATISTIQUE COMPL?TE
# ============================================================

def compute_returns(df):
    """Compute different return types"""
    df = df.copy()
    df['returns'] = df['Close'].pct_change()
    df['log_returns'] = np.log(df['Close'] / df['Close'].shift(1))
    df['abs_returns'] = df['returns'].abs()
    df['direction'] = (df['returns'] > 0).astype(int)
    return df.dropna()


def analyze_distribution(returns, name=""):
    """Analyze return distribution"""
    from scipy import stats

    results = {}
    results['count'] = len(returns)
    results['mean'] = returns.mean()
    results['std'] = returns.std()
    results['skewness'] = returns.skew()
    results['kurtosis'] = returns.kurtosis()  # Excess kurtosis
    results['min'] = returns.min()
    results['max'] = returns.max()

    # Percentiles
    for p in [1, 5, 25, 50, 75, 95, 99]:
        results[f'p{p}'] = np.percentile(returns, p)

    # Normality tests
    if len(returns) > 5000:
        sample = returns.sample(5000, random_state=42)
    else:
        sample = returns

    try:
        stat, p_val = stats.shapiro(sample[:5000] if len(sample) > 5000 else sample)
        results['shapiro_stat'] = stat
        results['shapiro_pvalue'] = p_val
    except:
        pass

    try:
        stat, p_val = stats.jarque_bera(returns)
        results['jarque_bera_stat'] = stat
        results['jarque_bera_pvalue'] = p_val
    except:
        pass

    # Fit different distributions
    try:
        # Normal
        norm_params = stats.norm.fit(returns)
        results['norm_fit_mean'] = norm_params[0]
        results['norm_fit_std'] = norm_params[1]

        # Student-t
        t_params = stats.t.fit(returns)
        results['t_df'] = t_params[0]
        results['t_loc'] = t_params[1]
        results['t_scale'] = t_params[2]

        # Compare via KS test
        ks_norm = stats.kstest(returns, 'norm', args=norm_params)
        ks_t = stats.kstest(returns, 't', args=t_params)
        results['ks_normal_pvalue'] = ks_norm.pvalue
        results['ks_student_pvalue'] = ks_t.pvalue
    except:
        pass

    return results


def analyze_autocorrelation(returns, max_lag=50):
    """Check if past returns predict future returns"""
    from statsmodels.tsa.stattools import acf, pacf

    results = {}

    # ACF
    acf_vals = acf(returns, nlags=max_lag, fft=True)
    results['acf_values'] = acf_vals.tolist()

    # Significant lags (outside 95% CI = ?1.96/sqrt(N))
    threshold = 1.96 / np.sqrt(len(returns))
    significant_lags = [i for i in range(1, len(acf_vals)) if abs(acf_vals[i]) > threshold]
    results['significant_acf_lags'] = significant_lags
    results['acf_threshold'] = threshold

    # ACF on absolute returns (volatility clustering)
    abs_acf = acf(returns.abs(), nlags=max_lag, fft=True)
    results['abs_acf_values'] = abs_acf.tolist()
    significant_abs_lags = [i for i in range(1, len(abs_acf)) if abs(abs_acf[i]) > threshold]
    results['significant_abs_acf_lags'] = significant_abs_lags

    # Ljung-Box test (are returns autocorrelated?)
    from statsmodels.stats.diagnostic import acorr_ljungbox
    lb_results = acorr_ljungbox(returns, lags=[10, 20, 50], return_df=True)
    results['ljung_box_p10'] = lb_results['lb_pvalue'].iloc[0]
    results['ljung_box_p20'] = lb_results['lb_pvalue'].iloc[1]
    results['ljung_box_p50'] = lb_results['lb_pvalue'].iloc[2]

    return results


def analyze_hurst(series, max_lag=100):
    """
    Hurst exponent via R/S analysis
    H < 0.5 : mean-reverting (EXPLOITABLE)
    H = 0.5 : random walk (not exploitable)
    H > 0.5 : trending (EXPLOITABLE)
    """
    lags = range(2, max_lag)
    rs_values = []

    for lag in lags:
        # Split into sub-series
        n = len(series)
        num_subseries = n // lag
        if num_subseries < 1:
            break

        rs_subseries = []
        for i in range(num_subseries):
            sub = series[i*lag:(i+1)*lag]
            if len(sub) < 2:
                continue

            mean_sub = sub.mean()
            deviations = sub - mean_sub
            cumulative = np.cumsum(deviations)

            R = cumulative.max() - cumulative.min()
            S = sub.std(ddof=1)

            if S > 0:
                rs_subseries.append(R / S)

        if rs_subseries:
            rs_values.append(np.mean(rs_subseries))

    # Fit log-log line
    valid_lags = list(lags)[:len(rs_values)]
    if len(valid_lags) > 5:
        log_lags = np.log(valid_lags)
        log_rs = np.log(rs_values)
        slope, intercept = np.polyfit(log_lags, log_rs, 1)
        return slope
    return 0.5


def analyze_stationarity(series):
    """ADF and KPSS tests for stationarity"""
    from statsmodels.tsa.stattools import adfuller, kpss

    results = {}

    # ADF test (H0: non-stationary)
    try:
        adf_result = adfuller(series, autolag='AIC')
        results['adf_statistic'] = adf_result[0]
        results['adf_pvalue'] = adf_result[1]
        results['adf_stationary'] = adf_result[1] < 0.05
    except:
        pass

    # KPSS test (H0: stationary)
    try:
        kpss_result = kpss(series, regression='c', nlags='auto')
        results['kpss_statistic'] = kpss_result[0]
        results['kpss_pvalue'] = kpss_result[1]
        results['kpss_stationary'] = kpss_result[1] > 0.05
    except:
        pass

    return results


def detect_spikes(df, threshold_std=3.0):
    """Detect spikes in Crash/Boom indices"""
    returns = df['returns']
    mean_ret = returns.mean()
    std_ret = returns.std()

    # Negative spikes (Crash)
    crash_threshold = mean_ret - threshold_std * std_ret
    crash_spikes = df[returns < crash_threshold].copy()

    # Positive spikes (Boom)
    boom_threshold = mean_ret + threshold_std * std_ret
    boom_spikes = df[returns > boom_threshold].copy()

    results = {
        'crash_threshold': crash_threshold,
        'boom_threshold': boom_threshold,
        'crash_count': len(crash_spikes),
        'boom_count': len(boom_spikes),
        'crash_mean_amplitude': crash_spikes['returns'].mean() if len(crash_spikes) > 0 else 0,
        'boom_mean_amplitude': boom_spikes['returns'].mean() if len(boom_spikes) > 0 else 0,
    }

    # Time between spikes (for Poisson analysis)
    if len(crash_spikes) > 1:
        crash_intervals = crash_spikes.index.to_series().diff().dt.total_seconds() / 3600  # hours
        crash_intervals = crash_intervals.dropna()
        results['crash_interval_mean_hours'] = crash_intervals.mean()
        results['crash_interval_std_hours'] = crash_intervals.std()
        results['crash_interval_median_hours'] = crash_intervals.median()

        # Test Poisson: if intervals are exponentially distributed -> Poisson process
        from scipy import stats
        if len(crash_intervals) > 10:
            exp_params = stats.expon.fit(crash_intervals)
            ks_stat, ks_pval = stats.kstest(crash_intervals, 'expon', args=exp_params)
            results['crash_poisson_ks_pvalue'] = ks_pval
            results['crash_is_poisson'] = ks_pval > 0.05

    if len(boom_spikes) > 1:
        boom_intervals = boom_spikes.index.to_series().diff().dt.total_seconds() / 3600
        boom_intervals = boom_intervals.dropna()
        results['boom_interval_mean_hours'] = boom_intervals.mean()
        results['boom_interval_std_hours'] = boom_intervals.std()

    # Pre-spike patterns (what happens before a spike?)
    if len(crash_spikes) > 5:
        pre_spike_returns = []
        for spike_idx in crash_spikes.index:
            # Get 10 candles before spike
            mask = df.index < spike_idx
            pre = df.loc[mask].tail(10)
            if len(pre) == 10:
                pre_spike_returns.append(pre['returns'].values)

        if pre_spike_returns:
            pre_spike_matrix = np.array(pre_spike_returns)
            mean_pre = pre_spike_matrix.mean(axis=0)
            results['pre_crash_pattern'] = mean_pre.tolist()
            results['pre_crash_mean_return'] = mean_pre.mean()
            # Is pre-spike behavior different from normal?
            normal_mean = returns.mean()
            results['pre_crash_bias'] = mean_pre.mean() - normal_mean

    return results, crash_spikes, boom_spikes


def analyze_temporal_patterns(df):
    """Check for time-of-day / day-of-week biases"""
    results = {}

    if hasattr(df.index, 'hour'):
        # Hourly analysis
        hourly = df.groupby(df.index.hour)['returns'].agg(['mean', 'std', 'count'])
        results['hourly_stats'] = hourly.to_dict()

        # Is there significant hourly variation?
        from scipy import stats
        hours_groups = [group['returns'].values for _, group in df.groupby(df.index.hour)]
        hours_groups = [g for g in hours_groups if len(g) > 10]
        if len(hours_groups) > 2:
            f_stat, f_pval = stats.f_oneway(*hours_groups)
            results['hourly_anova_pvalue'] = f_pval
            results['hourly_pattern_significant'] = f_pval < 0.05

        # Best and worst hours
        hourly_means = df.groupby(df.index.hour)['returns'].mean()
        results['best_hour'] = int(hourly_means.idxmax())
        results['worst_hour'] = int(hourly_means.idxmin())
        results['best_hour_return'] = hourly_means.max()
        results['worst_hour_return'] = hourly_means.min()

    if hasattr(df.index, 'dayofweek'):
        # Day of week analysis
        daily = df.groupby(df.index.dayofweek)['returns'].agg(['mean', 'std', 'count'])
        results['daily_stats'] = daily.to_dict()

        daily_groups = [group['returns'].values for _, group in df.groupby(df.index.dayofweek)]
        daily_groups = [g for g in daily_groups if len(g) > 10]
        if len(daily_groups) > 2:
            f_stat, f_pval = stats.f_oneway(*daily_groups)
            results['daily_anova_pvalue'] = f_pval
            results['daily_pattern_significant'] = f_pval < 0.05

    return results


def analyze_volatility_clustering(returns):
    """Check for ARCH/GARCH effects (volatility clustering)"""
    results = {}

    # ACF of squared returns
    from statsmodels.tsa.stattools import acf
    sq_returns = returns ** 2
    sq_acf = acf(sq_returns, nlags=20, fft=True)

    threshold = 1.96 / np.sqrt(len(returns))
    significant = [i for i in range(1, len(sq_acf)) if abs(sq_acf[i]) > threshold]

    results['squared_acf_significant_lags'] = significant
    results['volatility_clustering'] = len(significant) > 3
    results['sq_acf_lag1'] = sq_acf[1] if len(sq_acf) > 1 else 0

    # ARCH LM test
    from statsmodels.stats.diagnostic import het_arch
    try:
        lm_stat, lm_pval, f_stat, f_pval = het_arch(returns, nlags=10)
        results['arch_lm_pvalue'] = lm_pval
        results['arch_effect'] = lm_pval < 0.05
    except:
        pass

    return results


def compute_entropy(returns, bins=50):
    """Shannon entropy to measure randomness"""
    hist, _ = np.histogram(returns, bins=bins, density=True)
    hist = hist[hist > 0]
    # Normalize
    hist = hist / hist.sum()
    entropy = -np.sum(hist * np.log2(hist))

    # Maximum entropy for this number of bins
    max_entropy = np.log2(bins)
    normalized_entropy = entropy / max_entropy

    return {
        'shannon_entropy': entropy,
        'max_entropy': max_entropy,
        'normalized_entropy': normalized_entropy,
        'randomness': 'HIGH' if normalized_entropy > 0.9 else ('MEDIUM' if normalized_entropy > 0.7 else 'LOW')
    }


def analyze_consecutive_patterns(df):
    """Check if consecutive up/down moves follow patterns"""
    directions = df['direction'].values
    results = {}

    # Count consecutive runs
    runs = []
    current_run = 1
    for i in range(1, len(directions)):
        if directions[i] == directions[i-1]:
            current_run += 1
        else:
            runs.append(current_run)
            current_run = 1
    runs.append(current_run)

    results['mean_run_length'] = np.mean(runs)
    results['max_run_length'] = max(runs)

    # Expected for random: mean run = 2
    # If mean run > 2 -> trending; < 2 -> mean-reverting
    results['run_bias'] = 'TRENDING' if np.mean(runs) > 2.1 else ('MEAN_REVERTING' if np.mean(runs) < 1.9 else 'RANDOM')

    # Transition probabilities
    # P(up | previous up), P(down | previous down)
    up_after_up = 0
    down_after_down = 0
    count_after_up = 0
    count_after_down = 0

    for i in range(1, len(directions)):
        if directions[i-1] == 1:
            count_after_up += 1
            if directions[i] == 1:
                up_after_up += 1
        else:
            count_after_down += 1
            if directions[i] == 0:
                down_after_down += 1

    results['p_up_after_up'] = up_after_up / count_after_up if count_after_up > 0 else 0.5
    results['p_down_after_down'] = down_after_down / count_after_down if count_after_down > 0 else 0.5
    results['continuation_bias'] = (results['p_up_after_up'] + results['p_down_after_down']) / 2

    # If continuation_bias > 0.5 -> momentum
    # If continuation_bias < 0.5 -> mean reversion
    results['market_type'] = 'MOMENTUM' if results['continuation_bias'] > 0.52 else (
        'MEAN_REVERSION' if results['continuation_bias'] < 0.48 else 'RANDOM')

    return results


# ============================================================
# PARTIE 3 : RAPPORT FINAL
# ============================================================

def print_report(symbol, timeframe, df, all_results):
    """Print comprehensive analysis report"""
    dist = all_results['distribution']
    acorr = all_results['autocorrelation']
    hurst = all_results['hurst']
    station = all_results['stationarity']
    spikes = all_results['spikes']
    temporal = all_results['temporal']
    vol_cluster = all_results['volatility_clustering']
    entropy = all_results['entropy']
    consec = all_results['consecutive']

    print("\n" + "="*70)
    print(f"  ANALYSE STATISTIQUE : {symbol} - {timeframe}")
    print(f"  {len(df)} candles | {(df.index[-1] - df.index[0]).days} jours")
    print("="*70)

    # 1. Distribution
    print("\n--- DISTRIBUTION DES RETURNS ---")
    print(f"  Mean:      {dist['mean']:.6f}")
    print(f"  Std:       {dist['std']:.6f}")
    print(f"  Skewness:  {dist['skewness']:.4f}  {'(biais negatif=crashes)' if dist['skewness'] < -0.5 else '(biais positif=booms)' if dist['skewness'] > 0.5 else '(symetrique)'}")
    print(f"  Kurtosis:  {dist['kurtosis']:.4f}  {'(queues lourdes=spikes frequents)' if dist['kurtosis'] > 3 else '(normal)'}")
    jb_p = dist.get('jarque_bera_pvalue', 1)
    normality_str = f"NON (Jarque-Bera p={jb_p:.2e})" if jb_p < 0.05 else "OUI"
    print(f"  Normality: {normality_str}")
    if 'ks_student_pvalue' in dist:
        better_fit = "Student-t" if dist.get('ks_student_pvalue', 0) > dist.get('ks_normal_pvalue', 0) else "Normal"
        t_df = dist.get('t_df', 0)
        print(f"  Best fit:  {better_fit} (df={t_df:.1f})")

    # 2. Hurst
    print(f"\n--- HURST EXPONENT ---")
    print(f"  H = {hurst:.4f}")
    if hurst < 0.45:
        print(f"  >>> MEAN-REVERTING - SIGNAL EXPLOITABLE <<<")
    elif hurst > 0.55:
        print(f"  >>> TRENDING - SIGNAL EXPLOITABLE <<<")
    else:
        print(f"  ~Random walk - difficile ? exploiter")

    # 3. Autocorrelation
    print(f"\n--- AUTOCORR?LATION ---")
    sig_lags = acorr.get('significant_acf_lags', [])
    print(f"  Lags significatifs (returns): {sig_lags[:10] if sig_lags else 'AUCUN'}")
    sig_abs_lags = acorr.get('significant_abs_acf_lags', [])
    print(f"  Lags significatifs (|returns|): {sig_abs_lags[:10] if sig_abs_lags else 'AUCUN'}")
    print(f"  Ljung-Box p-value (lag 10): {acorr.get('ljung_box_p10', 'N/A'):.4f}")
    if acorr.get('ljung_box_p10', 1) < 0.05:
        print(f"  >>> AUTOCORR?LATION D?TECT?E - SIGNAL EXPLOITABLE <<<")

    # 4. Stationarity
    print(f"\n--- STATIONNARIT? ---")
    print(f"  ADF: {'Stationnaire' if station.get('adf_stationary') else 'Non-stationnaire'} (p={station.get('adf_pvalue', 'N/A'):.4f})")
    print(f"  KPSS: {'Stationnaire' if station.get('kpss_stationary') else 'Non-stationnaire'} (p={station.get('kpss_pvalue', 'N/A'):.4f})")

    # 5. Spikes (Crash/Boom)
    print(f"\n--- D?TECTION DE SPIKES ---")
    print(f"  Crashes (>{abs(spikes.get('crash_threshold', 0))*100:.2f}%): {spikes.get('crash_count', 0)}")
    print(f"  Booms (>{spikes.get('boom_threshold', 0)*100:.2f}%): {spikes.get('boom_count', 0)}")
    if spikes.get('crash_count', 0) > 0:
        print(f"  Crash amplitude moyenne: {spikes.get('crash_mean_amplitude', 0)*100:.3f}%")
    if spikes.get('crash_interval_mean_hours'):
        print(f"  Intervalle moyen crashes: {spikes['crash_interval_mean_hours']:.1f}h (?{spikes.get('crash_interval_std_hours', 0):.1f}h)")
        is_poisson = spikes.get('crash_is_poisson', 'N/A')
        print(f"  Distribution Poisson: {'OUI' if is_poisson == True else 'NON' if is_poisson == False else 'N/A'} (p={spikes.get('crash_poisson_ks_pvalue', 'N/A')})")
    if spikes.get('pre_crash_bias') is not None:
        bias = spikes['pre_crash_bias']
        print(f"  Biais pre-crash: {bias:.6f} {'(tendance baissiere avant crash)' if bias < 0 else '(pas de signal pre-crash)'}")

    # 6. Temporal patterns
    print(f"\n--- PATTERNS TEMPORELS ---")
    if temporal.get('hourly_pattern_significant'):
        print(f"  >>> PATTERN HORAIRE SIGNIFICATIF (p={temporal['hourly_anova_pvalue']:.4f}) <<<")
        print(f"  Meilleure heure: {temporal['best_hour']}h (return: {temporal['best_hour_return']*100:.4f}%)")
        print(f"  Pire heure: {temporal['worst_hour']}h (return: {temporal['worst_hour_return']*100:.4f}%)")
    else:
        print(f"  Pas de pattern horaire significatif (p={temporal.get('hourly_anova_pvalue', 'N/A')})")
    if temporal.get('daily_pattern_significant'):
        print(f"  >>> PATTERN JOURNALIER SIGNIFICATIF (p={temporal['daily_anova_pvalue']:.4f}) <<<")

    # 7. Volatility clustering
    print(f"\n--- CLUSTERING DE VOLATILIT? ---")
    print(f"  ARCH effect: {'OUI' if vol_cluster.get('arch_effect') else 'NON'} (p={vol_cluster.get('arch_lm_pvalue', 'N/A')})")
    print(f"  Volatility clustering: {'OUI' if vol_cluster.get('volatility_clustering') else 'NON'}")
    if vol_cluster.get('volatility_clustering'):
        print(f"  >>> LA VOLATILIT? EST PR?VISIBLE - EXPLOITABLE <<<")

    # 8. Entropy
    print(f"\n--- ENTROPIE ---")
    print(f"  Shannon: {entropy['shannon_entropy']:.4f} / {entropy['max_entropy']:.4f}")
    print(f"  Normalized: {entropy['normalized_entropy']:.4f}")
    print(f"  Randomness: {entropy['randomness']}")

    # 9. Consecutive patterns
    print(f"\n--- PATTERNS CONS?CUTIFS ---")
    print(f"  P(up|up):     {consec['p_up_after_up']:.4f} (random=0.50)")
    print(f"  P(down|down): {consec['p_down_after_down']:.4f} (random=0.50)")
    print(f"  Continuation: {consec['continuation_bias']:.4f}")
    print(f"  Run length:   {consec['mean_run_length']:.2f} (random=2.0)")
    print(f"  Type:         {consec['market_type']}")

    # ===== VERDICT =====
    print("\n" + "="*70)
    print("  VERDICT - SIGNAUX EXPLOITABLES")
    print("="*70)

    exploitable_signals = []

    if hurst < 0.45:
        exploitable_signals.append(f"Hurst={hurst:.3f} -> Mean Reversion (acheter bas, vendre haut)")
    elif hurst > 0.55:
        exploitable_signals.append(f"Hurst={hurst:.3f} -> Trend Following (suivre la tendance)")

    if acorr.get('ljung_box_p10', 1) < 0.05:
        exploitable_signals.append(f"Autocorrelation significative -> les returns passes predisent les futurs")

    if len(sig_abs_lags) > 3:
        exploitable_signals.append(f"Volatility clustering -> la volatilite est previsible (GARCH)")

    if temporal.get('hourly_pattern_significant'):
        exploitable_signals.append(f"Pattern horaire -> trader aux meilleures heures")

    if temporal.get('daily_pattern_significant'):
        exploitable_signals.append(f"Pattern journalier -> trader les meilleurs jours")

    if spikes.get('crash_is_poisson') == False:
        exploitable_signals.append(f"Spikes NON-Poisson -> il y a un pattern dans les crashes")

    if spikes.get('pre_crash_bias') and abs(spikes['pre_crash_bias']) > abs(dist['mean']):
        exploitable_signals.append(f"Signal pre-crash detecte -> possible anticipation des crashes")

    if consec['market_type'] != 'RANDOM':
        exploitable_signals.append(f"Biais {consec['market_type']} -> {consec['continuation_bias']:.3f}")

    if exploitable_signals:
        print(f"\n  TROUV? {len(exploitable_signals)} SIGNAL(S) EXPLOITABLE(S) :\n")
        for i, sig in enumerate(exploitable_signals, 1):
            print(f"  {i}. {sig}")
        print(f"\n  >>> RECOMMANDATION : Construire un modele base sur ces signaux <<<")
    else:
        print(f"\n  AUCUN signal exploitable clair trouve.")
        print(f"  L'indice semble etre un random walk pur.")
        print(f"  >>> RECOMMANDATION : Essayer d'autres timeframes ou indices <<<")

    print("\n" + "="*70)
    return exploitable_signals


# ============================================================
# MAIN
# ============================================================

async def main():
    # Configuration
    symbols_to_analyze = [
        ('Crash 500 Index', 'M15', 10000),
        ('Crash 500 Index', 'H1', 10000),
        ('Crash 500 Index', 'H4', 5000),
    ]

    output_dir = Path('data/raw')
    output_dir.mkdir(parents=True, exist_ok=True)
    Path('logs').mkdir(exist_ok=True)

    logger.add("logs/analysis.log", rotation="50 MB")

    all_signals = {}

    for symbol, timeframe, target in symbols_to_analyze:
        print(f"\n{'#'*70}")
        print(f"# EXTRACTION : {symbol} - {timeframe}")
        print(f"{'#'*70}")

        # Step 1: Extract
        df = await extract_symbol(symbol, timeframe, target)

        if df is None or len(df) < 100:
            print(f"  ERREUR: Pas assez de donnees extraites")
            continue

        # Save raw data
        filename = f"{symbol.replace(' ', '_')}_{timeframe}.parquet"
        df.to_parquet(output_dir / filename, compression='snappy')
        print(f"  Saved: {output_dir / filename}")

        # Step 2: Compute returns
        df = compute_returns(df)

        # Step 3: Full analysis
        print(f"\n  Running analysis on {len(df)} candles...")

        results = {}
        results['distribution'] = analyze_distribution(df['returns'])
        results['autocorrelation'] = analyze_autocorrelation(df['returns'])
        results['hurst'] = analyze_hurst(df['returns'].values)
        results['stationarity'] = analyze_stationarity(df['returns'])
        results['spikes'], crash_df, boom_df = detect_spikes(df)
        results['temporal'] = analyze_temporal_patterns(df)
        results['volatility_clustering'] = analyze_volatility_clustering(df['returns'])
        results['entropy'] = compute_entropy(df['returns'].values)
        results['consecutive'] = analyze_consecutive_patterns(df)

        # Step 4: Report
        signals = print_report(symbol, timeframe, df, results)
        all_signals[f"{symbol}_{timeframe}"] = signals

    # Final summary
    print("\n\n" + "#"*70)
    print("#" + " "*20 + "R?SUM? GLOBAL" + " "*20 + "#")
    print("#"*70)

    for key, signals in all_signals.items():
        print(f"\n  {key}: {len(signals)} signal(s)")
        for s in signals:
            print(f"    - {s}")

    print("\n" + "#"*70)


if __name__ == "__main__":
    asyncio.run(main())
