"""
Statistical Analyzer - Analyse statistique approfondie des séries temporelles
"""

import numpy as np
import pandas as pd
from scipy import stats
from scipy.fft import fft, fftfreq
from scipy.signal import find_peaks, welch
import pywt
from statsmodels.tsa.stattools import adfuller, kpss, acf, pacf
from statsmodels.stats.diagnostic import acorr_ljungbox
from arch.unitroot import PhillipsPerron
from typing import Dict, Tuple, Optional, List
from loguru import logger
import warnings

warnings.filterwarnings('ignore')


class StatisticalAnalyzer:
    """Classe pour l'analyse statistique des séries temporelles"""

    def __init__(self, data: pd.DataFrame, price_column: str = 'Close'):
        """
        Initialize Statistical Analyzer

        Args:
            data: DataFrame with OHLCV data
            price_column: Column to analyze
        """
        self.data = data.copy()
        self.price_column = price_column
        self.prices = data[price_column].values
        self.returns = self._calculate_returns()
        self.log_returns = self._calculate_log_returns()

    def _calculate_returns(self) -> np.ndarray:
        """Calculate simple returns"""
        return np.diff(self.prices) / self.prices[:-1]

    def _calculate_log_returns(self) -> np.ndarray:
        """Calculate log returns"""
        return np.diff(np.log(self.prices))

    def analyze_distribution(self) -> Dict:
        """
        Analyze the distribution of returns

        Returns:
            Dictionary with distribution statistics
        """
        logger.info("Analyzing distribution...")

        results = {}

        # Basic statistics
        results['mean'] = float(np.mean(self.returns))
        results['std'] = float(np.std(self.returns))
        results['variance'] = float(np.var(self.returns))
        results['skewness'] = float(stats.skew(self.returns))
        results['kurtosis'] = float(stats.kurtosis(self.returns))
        results['min'] = float(np.min(self.returns))
        results['max'] = float(np.max(self.returns))

        # Percentiles
        results['percentiles'] = {
            '1%': float(np.percentile(self.returns, 1)),
            '5%': float(np.percentile(self.returns, 5)),
            '25%': float(np.percentile(self.returns, 25)),
            '50%': float(np.percentile(self.returns, 50)),
            '75%': float(np.percentile(self.returns, 75)),
            '95%': float(np.percentile(self.returns, 95)),
            '99%': float(np.percentile(self.returns, 99)),
        }

        # Normality tests
        results['normality'] = {}

        # Shapiro-Wilk test (sample size limited)
        if len(self.returns) <= 5000:
            stat, p_value = stats.shapiro(self.returns)
            results['normality']['shapiro'] = {
                'statistic': float(stat),
                'p_value': float(p_value),
                'is_normal': p_value > 0.05
            }

        # Jarque-Bera test
        stat, p_value = stats.jarque_bera(self.returns)
        results['normality']['jarque_bera'] = {
            'statistic': float(stat),
            'p_value': float(p_value),
            'is_normal': p_value > 0.05
        }

        # Anderson-Darling test
        result = stats.anderson(self.returns, dist='norm')
        results['normality']['anderson'] = {
            'statistic': float(result.statistic),
            'critical_values': result.critical_values.tolist(),
            'significance_level': result.significance_level.tolist()
        }

        # Kolmogorov-Smirnov test
        stat, p_value = stats.kstest(self.returns, 'norm')
        results['normality']['ks_test'] = {
            'statistic': float(stat),
            'p_value': float(p_value),
            'is_normal': p_value > 0.05
        }

        # Test against other distributions
        results['distribution_fitting'] = {}

        # Student's t-distribution
        params = stats.t.fit(self.returns)
        ks_stat, ks_p = stats.kstest(self.returns, lambda x: stats.t.cdf(x, *params))
        results['distribution_fitting']['student_t'] = {
            'params': params,
            'ks_statistic': float(ks_stat),
            'ks_p_value': float(ks_p)
        }

        # Laplace distribution
        params = stats.laplace.fit(self.returns)
        ks_stat, ks_p = stats.kstest(self.returns, lambda x: stats.laplace.cdf(x, *params))
        results['distribution_fitting']['laplace'] = {
            'params': params,
            'ks_statistic': float(ks_stat),
            'ks_p_value': float(ks_p)
        }

        # Cauchy distribution
        params = stats.cauchy.fit(self.returns)
        ks_stat, ks_p = stats.kstest(self.returns, lambda x: stats.cauchy.cdf(x, *params))
        results['distribution_fitting']['cauchy'] = {
            'params': params,
            'ks_statistic': float(ks_stat),
            'ks_p_value': float(ks_p)
        }

        return results

    def test_stationarity(self) -> Dict:
        """
        Test stationarity of the time series

        Returns:
            Dictionary with stationarity test results
        """
        logger.info("Testing stationarity...")

        results = {}

        # Augmented Dickey-Fuller test
        adf_result = adfuller(self.prices, autolag='AIC')
        results['adf'] = {
            'statistic': float(adf_result[0]),
            'p_value': float(adf_result[1]),
            'used_lag': int(adf_result[2]),
            'n_obs': int(adf_result[3]),
            'critical_values': adf_result[4],
            'is_stationary': adf_result[1] < 0.05
        }

        # KPSS test
        kpss_result = kpss(self.prices, regression='ct', nlags='auto')
        results['kpss'] = {
            'statistic': float(kpss_result[0]),
            'p_value': float(kpss_result[1]),
            'used_lag': int(kpss_result[2]),
            'critical_values': kpss_result[3],
            'is_stationary': kpss_result[1] > 0.05
        }

        # Phillips-Perron test
        pp_result = PhillipsPerron(self.prices)
        results['phillips_perron'] = {
            'statistic': float(pp_result.stat),
            'p_value': float(pp_result.pvalue),
            'is_stationary': pp_result.pvalue < 0.05
        }

        # Test on returns
        adf_returns = adfuller(self.returns, autolag='AIC')
        results['adf_returns'] = {
            'statistic': float(adf_returns[0]),
            'p_value': float(adf_returns[1]),
            'is_stationary': adf_returns[1] < 0.05
        }

        return results

    def analyze_autocorrelation(self, max_lags: int = 100) -> Dict:
        """
        Analyze autocorrelation

        Args:
            max_lags: Maximum number of lags

        Returns:
            Dictionary with autocorrelation results
        """
        logger.info("Analyzing autocorrelation...")

        results = {}

        # ACF
        acf_values = acf(self.returns, nlags=max_lags, fft=True)
        results['acf'] = acf_values.tolist()

        # PACF
        pacf_values = pacf(self.returns, nlags=max_lags)
        results['pacf'] = pacf_values.tolist()

        # Ljung-Box test
        lb_test = acorr_ljungbox(self.returns, lags=min(20, len(self.returns) // 5), return_df=True)
        results['ljung_box'] = {
            'statistics': lb_test['lb_stat'].tolist(),
            'p_values': lb_test['lb_pvalue'].tolist(),
            'has_autocorrelation': any(lb_test['lb_pvalue'] < 0.05)
        }

        # Find significant lags
        significant_lags = np.where(np.abs(acf_values[1:]) > 1.96 / np.sqrt(len(self.returns)))[0] + 1
        results['significant_lags'] = significant_lags.tolist()

        return results

    def calculate_hurst_exponent(self, lags: List[int] = None) -> Dict:
        """
        Calculate Hurst exponent to determine if series is trending, mean-reverting, or random

        H < 0.5: Mean reverting
        H = 0.5: Random walk (Brownian motion)
        H > 0.5: Trending

        Args:
            lags: List of lags to use

        Returns:
            Dictionary with Hurst exponent results
        """
        logger.info("Calculating Hurst exponent...")

        if lags is None:
            lags = [10, 20, 50, 100, 200]

        # Filter valid lags
        lags = [lag for lag in lags if lag < len(self.prices) // 2]

        tau = []
        lagvec = []

        for lag in lags:
            # Calculate the array of the moving average
            pp = np.subtract(self.prices[lag:], self.prices[:-lag])
            lagvec.append(lag)
            tau.append(np.std(pp))

        # Linear fit
        m = np.polyfit(np.log(lagvec), np.log(tau), 1)
        hurst = m[0]

        result = {
            'hurst_exponent': float(hurst),
            'interpretation': self._interpret_hurst(hurst),
            'lags_used': lagvec,
            'std_values': tau
        }

        return result

    def _interpret_hurst(self, hurst: float) -> str:
        """Interpret Hurst exponent value"""
        if hurst < 0.4:
            return "Strong mean reversion"
        elif hurst < 0.5:
            return "Mean reverting"
        elif hurst < 0.6:
            return "Random walk (no memory)"
        elif hurst < 0.7:
            return "Trending"
        else:
            return "Strong trending / persistent"

    def analyze_frequency(self, detrend: bool = True) -> Dict:
        """
        Frequency analysis using FFT

        Args:
            detrend: Whether to detrend the signal first

        Returns:
            Dictionary with frequency analysis results
        """
        logger.info("Analyzing frequency components...")

        # Prepare signal
        signal = self.prices.copy()

        if detrend:
            # Remove linear trend
            x = np.arange(len(signal))
            coeffs = np.polyfit(x, signal, 1)
            trend = np.polyval(coeffs, x)
            signal = signal - trend

        # Apply window to reduce spectral leakage
        window = np.hamming(len(signal))
        signal = signal * window

        # Compute FFT
        fft_values = fft(signal)
        fft_freq = fftfreq(len(signal))

        # Power spectrum
        power = np.abs(fft_values) ** 2

        # Keep only positive frequencies
        positive_freq_idx = fft_freq > 0
        frequencies = fft_freq[positive_freq_idx]
        power = power[positive_freq_idx]

        # Find peaks
        peaks, properties = find_peaks(power, height=np.percentile(power, 95))

        # Get dominant frequencies
        dominant_indices = np.argsort(power[peaks])[-10:]
        dominant_frequencies = frequencies[peaks[dominant_indices]]
        dominant_powers = power[peaks[dominant_indices]]

        # Convert to periods (in bars)
        dominant_periods = [1 / f if f != 0 else np.inf for f in dominant_frequencies]

        results = {
            'frequencies': frequencies.tolist(),
            'power_spectrum': power.tolist(),
            'dominant_frequencies': dominant_frequencies.tolist(),
            'dominant_periods': dominant_periods,
            'dominant_powers': dominant_powers.tolist(),
            'peak_indices': peaks.tolist()
        }

        return results

    def wavelet_analysis(self, wavelet: str = 'morl', scales: int = 128) -> Dict:
        """
        Wavelet analysis for multi-scale pattern detection

        Args:
            wavelet: Wavelet type (morl, mexh, db4, etc.)
            scales: Number of scales

        Returns:
            Dictionary with wavelet analysis results
        """
        logger.info("Performing wavelet analysis...")

        # Generate scales
        scales_array = np.arange(1, scales)

        # Continuous wavelet transform
        coefficients, frequencies = pywt.cwt(self.prices, scales_array, wavelet)

        # Calculate power
        power = np.abs(coefficients) ** 2

        results = {
            'scales': scales_array.tolist(),
            'frequencies': frequencies.tolist(),
            'coefficients_shape': coefficients.shape,
            'power_shape': power.shape,
            'max_power_scale': int(np.argmax(np.mean(power, axis=1)))
        }

        return results

    def calculate_entropy(self) -> Dict:
        """
        Calculate various entropy measures to assess randomness

        Returns:
            Dictionary with entropy measures
        """
        logger.info("Calculating entropy measures...")

        results = {}

        # Shannon entropy
        hist, bin_edges = np.histogram(self.returns, bins=50, density=True)
        hist = hist[hist > 0]  # Remove zeros
        shannon_entropy = -np.sum(hist * np.log2(hist))
        results['shannon_entropy'] = float(shannon_entropy)

        # Sample entropy
        results['sample_entropy'] = self._sample_entropy(self.returns, m=2, r=0.2)

        # Approximate entropy
        results['approximate_entropy'] = self._approximate_entropy(self.returns, m=2, r=0.2)

        return results

    def _sample_entropy(self, data: np.ndarray, m: int, r: float) -> float:
        """Calculate sample entropy"""
        N = len(data)
        r = r * np.std(data)

        def _maxdist(xi, xj):
            return max([abs(ua - va) for ua, va in zip(xi, xj)])

        def _phi(m):
            x = [[data[j] for j in range(i, i + m - 1 + 1)] for i in range(N - m + 1)]
            C = [len([1 for x_j in x if _maxdist(x_i, x_j) <= r]) / (N - m + 1.0) for x_i in x]
            return sum(C) / (N - m + 1.0)

        return -np.log(_phi(m + 1) / _phi(m))

    def _approximate_entropy(self, data: np.ndarray, m: int, r: float) -> float:
        """Calculate approximate entropy"""
        N = len(data)
        r = r * np.std(data)

        def _maxdist(xi, xj):
            return max([abs(ua - va) for ua, va in zip(xi, xj)])

        def _phi(m):
            x = [[data[j] for j in range(i, i + m - 1 + 1)] for i in range(N - m + 1)]
            C = [len([1 for x_j in x if _maxdist(x_i, x_j) <= r]) / (N - m + 1.0) for x_i in x]
            return (N - m + 1.0) ** (-1) * sum(np.log(C))

        return abs(_phi(m) - _phi(m + 1))

    def full_analysis(self) -> Dict:
        """
        Perform complete statistical analysis

        Returns:
            Dictionary with all analysis results
        """
        logger.info("Starting full statistical analysis...")

        results = {
            'distribution': self.analyze_distribution(),
            'stationarity': self.test_stationarity(),
            'autocorrelation': self.analyze_autocorrelation(),
            'hurst_exponent': self.calculate_hurst_exponent(),
            'frequency': self.analyze_frequency(),
            'entropy': self.calculate_entropy(),
            'summary': self._generate_summary()
        }

        logger.info("Statistical analysis complete!")

        return results

    def _generate_summary(self) -> Dict:
        """Generate a human-readable summary"""
        return {
            'total_observations': len(self.prices),
            'time_period': {
                'start': str(self.data.index[0]),
                'end': str(self.data.index[-1]),
                'duration': str(self.data.index[-1] - self.data.index[0])
            },
            'price_range': {
                'min': float(np.min(self.prices)),
                'max': float(np.max(self.prices)),
                'range': float(np.max(self.prices) - np.min(self.prices))
            },
            'volatility': {
                'daily': float(np.std(self.returns) * np.sqrt(252)),  # Annualized
                'returns_std': float(np.std(self.returns))
            }
        }


def main():
    """Example usage"""
    # Load sample data
    data = pd.read_parquet("data/raw/Volatility_10_Index_M1.parquet")

    # Create analyzer
    analyzer = StatisticalAnalyzer(data, price_column='Close')

    # Full analysis
    results = analyzer.full_analysis()

    # Print summary
    print("\n=== STATISTICAL ANALYSIS SUMMARY ===\n")
    print(f"Total observations: {results['summary']['total_observations']}")
    print(f"Period: {results['summary']['time_period']['start']} to {results['summary']['time_period']['end']}")
    print(f"\nDistribution:")
    print(f"  Mean: {results['distribution']['mean']:.6f}")
    print(f"  Std: {results['distribution']['std']:.6f}")
    print(f"  Skewness: {results['distribution']['skewness']:.4f}")
    print(f"  Kurtosis: {results['distribution']['kurtosis']:.4f}")
    print(f"\nStationarity:")
    print(f"  ADF test: {'Stationary' if results['stationarity']['adf']['is_stationary'] else 'Non-stationary'}")
    print(f"  KPSS test: {'Stationary' if results['stationarity']['kpss']['is_stationary'] else 'Non-stationary'}")
    print(f"\nHurst Exponent: {results['hurst_exponent']['hurst_exponent']:.4f}")
    print(f"  Interpretation: {results['hurst_exponent']['interpretation']}")


if __name__ == "__main__":
    main()
