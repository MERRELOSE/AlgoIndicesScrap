"""
Pattern Detector - Détection de patterns spécifiques aux indices synthétiques
"""

import numpy as np
import pandas as pd
from scipy.signal import find_peaks, argrelextrema
from scipy.stats import poisson
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import ruptures as rpt
from typing import Dict, List, Tuple, Optional
from loguru import logger


class PatternDetector:
    """Détection de patterns algorithmiques dans les indices synthétiques"""

    def __init__(self, data: pd.DataFrame, price_column: str = 'Close'):
        """
        Initialize Pattern Detector

        Args:
            data: DataFrame with OHLCV data
            price_column: Column to analyze
        """
        self.data = data.copy()
        self.price_column = price_column
        self.prices = data[price_column].values
        self.returns = self._calculate_returns()

    def _calculate_returns(self) -> np.ndarray:
        """Calculate returns"""
        return np.diff(self.prices) / self.prices[:-1]

    def detect_spikes(
        self,
        threshold_std: float = 3.0,
        min_distance: int = 10,
        spike_type: str = 'both'
    ) -> Dict:
        """
        Detect artificial spikes (for Crash/Boom indices)

        Args:
            threshold_std: Number of standard deviations for spike detection
            min_distance: Minimum distance between spikes (in bars)
            spike_type: 'crash' (negative), 'boom' (positive), or 'both'

        Returns:
            Dictionary with spike information
        """
        logger.info(f"Detecting {spike_type} spikes...")

        returns = self.returns
        mean = np.mean(returns)
        std = np.std(returns)

        # Define spike thresholds
        upper_threshold = mean + threshold_std * std
        lower_threshold = mean - threshold_std * std

        # Detect spikes
        crash_spikes = []
        boom_spikes = []

        if spike_type in ['crash', 'both']:
            crash_indices = np.where(returns < lower_threshold)[0]
            if len(crash_indices) > 0:
                # Filter by minimum distance
                filtered = [crash_indices[0]]
                for idx in crash_indices[1:]:
                    if idx - filtered[-1] >= min_distance:
                        filtered.append(idx)
                crash_spikes = filtered

        if spike_type in ['boom', 'both']:
            boom_indices = np.where(returns > upper_threshold)[0]
            if len(boom_indices) > 0:
                # Filter by minimum distance
                filtered = [boom_indices[0]]
                for idx in boom_indices[1:]:
                    if idx - filtered[-1] >= min_distance:
                        filtered.append(idx)
                boom_spikes = filtered

        # Calculate spike statistics
        results = {
            'crash_spikes': {
                'count': len(crash_spikes),
                'indices': crash_spikes,
                'magnitudes': [float(returns[i]) for i in crash_spikes] if crash_spikes else [],
                'timestamps': [str(self.data.index[i+1]) for i in crash_spikes] if crash_spikes else []
            },
            'boom_spikes': {
                'count': len(boom_spikes),
                'indices': boom_spikes,
                'magnitudes': [float(returns[i]) for i in boom_spikes] if boom_spikes else [],
                'timestamps': [str(self.data.index[i+1]) for i in boom_spikes] if boom_spikes else []
            }
        }

        # Analyze spike timing
        if crash_spikes:
            intervals = np.diff(crash_spikes)
            results['crash_spikes']['timing'] = {
                'mean_interval': float(np.mean(intervals)),
                'std_interval': float(np.std(intervals)),
                'min_interval': int(np.min(intervals)),
                'max_interval': int(np.max(intervals))
            }

            # Test if follows Poisson distribution
            lambda_param = len(crash_spikes) / len(self.prices)
            results['crash_spikes']['poisson_test'] = self._test_poisson_distribution(
                intervals, lambda_param
            )

        if boom_spikes:
            intervals = np.diff(boom_spikes)
            results['boom_spikes']['timing'] = {
                'mean_interval': float(np.mean(intervals)),
                'std_interval': float(np.std(intervals)),
                'min_interval': int(np.min(intervals)),
                'max_interval': int(np.max(intervals))
            }

            lambda_param = len(boom_spikes) / len(self.prices)
            results['boom_spikes']['poisson_test'] = self._test_poisson_distribution(
                intervals, lambda_param
            )

        return results

    def _test_poisson_distribution(self, intervals: np.ndarray, lambda_param: float) -> Dict:
        """Test if intervals follow a Poisson distribution"""
        # Expected frequencies under Poisson
        max_interval = int(np.max(intervals))
        observed, bin_edges = np.histogram(intervals, bins=range(max_interval + 2))

        # Expected under Poisson
        expected = [poisson.pmf(k, lambda_param) * len(intervals) for k in range(max_interval + 1)]

        return {
            'lambda': float(lambda_param),
            'mean_observed': float(np.mean(intervals)),
            'mean_expected': float(1 / lambda_param if lambda_param > 0 else 0)
        }

    def detect_cycles(
        self,
        min_period: int = 10,
        max_period: int = 500
    ) -> Dict:
        """
        Detect cyclical patterns

        Args:
            min_period: Minimum cycle period (in bars)
            max_period: Maximum cycle period (in bars)

        Returns:
            Dictionary with cycle information
        """
        logger.info("Detecting cycles...")

        from scipy.signal import find_peaks
        from scipy.fft import fft, fftfreq

        # Detrend the signal
        x = np.arange(len(self.prices))
        coeffs = np.polyfit(x, self.prices, 1)
        trend = np.polyval(coeffs, x)
        detrended = self.prices - trend

        # FFT
        fft_values = fft(detrended)
        frequencies = fftfreq(len(detrended))

        # Power spectrum
        power = np.abs(fft_values) ** 2

        # Keep only positive frequencies
        positive_freq_idx = frequencies > 0
        frequencies = frequencies[positive_freq_idx]
        power = power[positive_freq_idx]

        # Convert to periods
        periods = 1 / frequencies

        # Filter by period range
        valid_idx = (periods >= min_period) & (periods <= max_period)
        periods = periods[valid_idx]
        power = power[valid_idx]

        # Find peaks in power spectrum
        peaks, properties = find_peaks(power, height=np.percentile(power, 90))

        # Get top cycles
        top_cycles = []
        if len(peaks) > 0:
            sorted_indices = np.argsort(power[peaks])[-10:]  # Top 10
            for idx in sorted_indices:
                peak_idx = peaks[idx]
                top_cycles.append({
                    'period': float(periods[peak_idx]),
                    'power': float(power[peak_idx]),
                    'frequency': float(frequencies[peak_idx])
                })

        results = {
            'detected_cycles': top_cycles,
            'num_cycles': len(top_cycles),
            'dominant_cycle': top_cycles[-1] if top_cycles else None
        }

        return results

    def detect_change_points(
        self,
        model: str = 'rbf',
        min_size: int = 20,
        jump: int = 5,
        n_bkps: int = 10
    ) -> Dict:
        """
        Detect change points (regime changes) - useful for Step Index

        Args:
            model: Change point detection model ('rbf', 'l1', 'l2', 'normal')
            min_size: Minimum segment size
            jump: Subsample parameter
            n_bkps: Number of breakpoints to detect

        Returns:
            Dictionary with change point information
        """
        logger.info("Detecting change points...")

        # Use ruptures library
        signal = self.prices.reshape(-1, 1)

        # Choose algorithm
        algo = rpt.Pelt(model=model, min_size=min_size, jump=jump).fit(signal)

        try:
            # Detect change points
            breakpoints = algo.predict(pen=10)

            # Calculate statistics for each segment
            segments = []
            prev_bp = 0
            for bp in breakpoints:
                segment_data = self.prices[prev_bp:bp]
                segments.append({
                    'start': prev_bp,
                    'end': bp,
                    'length': bp - prev_bp,
                    'mean': float(np.mean(segment_data)),
                    'std': float(np.std(segment_data)),
                    'trend': 'up' if segment_data[-1] > segment_data[0] else 'down'
                })
                prev_bp = bp

            results = {
                'num_breakpoints': len(breakpoints),
                'breakpoints': breakpoints,
                'segments': segments,
                'timestamps': [str(self.data.index[bp]) for bp in breakpoints[:-1]]
            }

        except Exception as e:
            logger.error(f"Change point detection failed: {e}")
            results = {
                'num_breakpoints': 0,
                'breakpoints': [],
                'segments': [],
                'error': str(e)
            }

        return results

    def detect_anomalies(
        self,
        method: str = 'isolation_forest',
        contamination: float = 0.1,
        window: int = 20
    ) -> Dict:
        """
        Detect anomalies in the time series

        Args:
            method: Detection method ('isolation_forest', 'zscore', 'iqr')
            contamination: Expected proportion of anomalies
            window: Window size for rolling statistics

        Returns:
            Dictionary with anomaly information
        """
        logger.info(f"Detecting anomalies using {method}...")

        if method == 'isolation_forest':
            # Prepare features
            features = self._create_anomaly_features(window)

            # Scale features
            scaler = StandardScaler()
            features_scaled = scaler.fit_transform(features)

            # Train Isolation Forest
            iso_forest = IsolationForest(
                contamination=contamination,
                random_state=42,
                n_estimators=100
            )

            # Predict anomalies (-1 = anomaly, 1 = normal)
            predictions = iso_forest.fit_predict(features_scaled)

            # Get anomaly scores
            scores = iso_forest.score_samples(features_scaled)

            anomaly_indices = np.where(predictions == -1)[0]

        elif method == 'zscore':
            # Z-score method
            rolling_mean = pd.Series(self.returns).rolling(window=window).mean()
            rolling_std = pd.Series(self.returns).rolling(window=window).std()
            z_scores = np.abs((self.returns - rolling_mean) / rolling_std)

            threshold = 3.0
            anomaly_indices = np.where(z_scores > threshold)[0]
            scores = -z_scores.values

        elif method == 'iqr':
            # Interquartile Range method
            Q1 = np.percentile(self.returns, 25)
            Q3 = np.percentile(self.returns, 75)
            IQR = Q3 - Q1

            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR

            anomaly_indices = np.where(
                (self.returns < lower_bound) | (self.returns > upper_bound)
            )[0]
            scores = None

        else:
            raise ValueError(f"Unknown method: {method}")

        results = {
            'method': method,
            'num_anomalies': len(anomaly_indices),
            'anomaly_indices': anomaly_indices.tolist(),
            'anomaly_ratio': len(anomaly_indices) / len(self.prices),
            'timestamps': [str(self.data.index[i]) for i in anomaly_indices],
            'scores': scores.tolist() if scores is not None else None
        }

        return results

    def _create_anomaly_features(self, window: int) -> np.ndarray:
        """Create features for anomaly detection"""
        df = pd.DataFrame({'price': self.prices, 'return': np.append(0, self.returns)})

        # Rolling statistics
        df['rolling_mean'] = df['return'].rolling(window=window).mean()
        df['rolling_std'] = df['return'].rolling(window=window).std()
        df['rolling_min'] = df['return'].rolling(window=window).min()
        df['rolling_max'] = df['return'].rolling(window=window).max()

        # Distance from rolling mean
        df['distance_from_mean'] = np.abs(df['return'] - df['rolling_mean'])

        # Volatility
        df['volatility'] = df['return'].rolling(window=window).std()

        # Fill NaN values
        df.fillna(method='bfill', inplace=True)

        features = df[['rolling_mean', 'rolling_std', 'distance_from_mean', 'volatility']].values

        return features

    def analyze_time_patterns(self) -> Dict:
        """
        Analyze time-based patterns (hourly, daily, weekly)

        Returns:
            Dictionary with time-based statistics
        """
        logger.info("Analyzing time patterns...")

        df = self.data.copy()
        df['return'] = np.append(0, self.returns)

        results = {}

        # Hour of day analysis
        if hasattr(df.index, 'hour'):
            hour_stats = df.groupby(df.index.hour)['return'].agg(['mean', 'std', 'count'])
            results['hourly'] = {
                'mean': hour_stats['mean'].to_dict(),
                'std': hour_stats['std'].to_dict(),
                'count': hour_stats['count'].to_dict()
            }

        # Day of week analysis
        if hasattr(df.index, 'dayofweek'):
            dow_stats = df.groupby(df.index.dayofweek)['return'].agg(['mean', 'std', 'count'])
            results['day_of_week'] = {
                'mean': dow_stats['mean'].to_dict(),
                'std': dow_stats['std'].to_dict(),
                'count': dow_stats['count'].to_dict()
            }

        # Day of month analysis
        if hasattr(df.index, 'day'):
            dom_stats = df.groupby(df.index.day)['return'].agg(['mean', 'std', 'count'])
            results['day_of_month'] = {
                'mean': dom_stats['mean'].to_dict(),
                'std': dom_stats['std'].to_dict(),
                'count': dom_stats['count'].to_dict()
            }

        return results

    def detect_mean_reversion_patterns(self, threshold: float = 0.5) -> Dict:
        """
        Detect mean reversion patterns

        Args:
            threshold: Threshold for mean reversion strength

        Returns:
            Dictionary with mean reversion statistics
        """
        logger.info("Detecting mean reversion patterns...")

        # Calculate distance from moving average
        window = 20
        ma = pd.Series(self.prices).rolling(window=window).mean().values

        # Distance from MA
        distance = self.prices - ma

        # Identify reversions
        # When price is above MA and then goes below, or vice versa
        sign_changes = np.diff(np.sign(distance))

        reversion_points = np.where(sign_changes != 0)[0]

        # Calculate reversion statistics
        if len(reversion_points) > 1:
            intervals = np.diff(reversion_points)
            mean_interval = float(np.mean(intervals))
            std_interval = float(np.std(intervals))
        else:
            mean_interval = 0
            std_interval = 0

        results = {
            'num_reversions': len(reversion_points),
            'reversion_points': reversion_points.tolist(),
            'mean_interval': mean_interval,
            'std_interval': std_interval,
            'max_distance': float(np.max(np.abs(distance[window:]))),
            'mean_distance': float(np.mean(np.abs(distance[window:])))
        }

        return results

    def full_pattern_analysis(
        self,
        spike_threshold: float = 3.0,
        enable_cycles: bool = True,
        enable_changepoints: bool = True
    ) -> Dict:
        """
        Perform complete pattern analysis

        Args:
            spike_threshold: Threshold for spike detection
            enable_cycles: Whether to perform cycle detection
            enable_changepoints: Whether to perform change point detection

        Returns:
            Dictionary with all pattern analysis results
        """
        logger.info("Starting full pattern analysis...")

        results = {
            'spikes': self.detect_spikes(threshold_std=spike_threshold),
            'anomalies': self.detect_anomalies(),
            'time_patterns': self.analyze_time_patterns(),
            'mean_reversion': self.detect_mean_reversion_patterns()
        }

        if enable_cycles:
            results['cycles'] = self.detect_cycles()

        if enable_changepoints:
            results['change_points'] = self.detect_change_points()

        logger.info("Pattern analysis complete!")

        return results


def main():
    """Example usage"""
    # Load sample data
    data = pd.read_parquet("data/raw/Crash_500_Index_M1.parquet")

    # Create detector
    detector = PatternDetector(data, price_column='Close')

    # Full analysis
    results = detector.full_pattern_analysis()

    # Print summary
    print("\n=== PATTERN ANALYSIS SUMMARY ===\n")
    print(f"Crash spikes detected: {results['spikes']['crash_spikes']['count']}")
    print(f"Boom spikes detected: {results['spikes']['boom_spikes']['count']}")
    print(f"Anomalies detected: {results['anomalies']['num_anomalies']}")

    if 'cycles' in results and results['cycles']['dominant_cycle']:
        print(f"Dominant cycle period: {results['cycles']['dominant_cycle']['period']:.1f} bars")

    if 'change_points' in results:
        print(f"Change points detected: {results['change_points']['num_breakpoints']}")


if __name__ == "__main__":
    main()
