"""
Helper functions and utilities
"""

import pandas as pd
import numpy as np
import yaml
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger


def load_config(config_path: str = "config/config.yaml") -> dict:
    """
    Load configuration from YAML file

    Args:
        config_path: Path to config file

    Returns:
        Configuration dictionary
    """
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def setup_logging(
    log_file: str = "logs/app.log",
    level: str = "INFO",
    rotation: str = "100 MB",
    retention: str = "30 days"
):
    """
    Setup logging configuration

    Args:
        log_file: Path to log file
        level: Logging level
        rotation: Log rotation size
        retention: Log retention period
    """
    # Create logs directory
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    # Remove default handler
    logger.remove()

    # Add console handler
    logger.add(
        lambda msg: print(msg, end=""),
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    )

    # Add file handler
    logger.add(
        log_file,
        level=level,
        rotation=rotation,
        retention=retention,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
    )


def load_data(
    symbol: str,
    timeframe: str = "M1",
    data_dir: str = "data/raw"
) -> Optional[pd.DataFrame]:
    """
    Load data from parquet file

    Args:
        symbol: Symbol name
        timeframe: Timeframe
        data_dir: Data directory

    Returns:
        DataFrame or None
    """
    filename = f"{symbol.replace(' ', '_')}_{timeframe}.parquet"
    filepath = Path(data_dir) / filename

    if not filepath.exists():
        logger.error(f"File not found: {filepath}")
        return None

    df = pd.read_parquet(filepath)
    logger.info(f"Loaded {len(df)} rows from {filepath}")

    return df


def calculate_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate common technical indicators

    Args:
        df: DataFrame with OHLCV data

    Returns:
        DataFrame with added indicators
    """
    df = df.copy()

    # Simple Moving Averages
    for period in [10, 20, 50, 100, 200]:
        df[f'SMA_{period}'] = df['Close'].rolling(window=period).mean()

    # Exponential Moving Averages
    for period in [10, 20, 50]:
        df[f'EMA_{period}'] = df['Close'].ewm(span=period, adjust=False).mean()

    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # MACD
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_hist'] = df['MACD'] - df['MACD_signal']

    # Bollinger Bands
    df['BB_middle'] = df['Close'].rolling(window=20).mean()
    bb_std = df['Close'].rolling(window=20).std()
    df['BB_upper'] = df['BB_middle'] + (bb_std * 2)
    df['BB_lower'] = df['BB_middle'] - (bb_std * 2)

    # ATR (Average True Range)
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['ATR'] = true_range.rolling(14).mean()

    # Stochastic Oscillator
    low_14 = df['Low'].rolling(window=14).min()
    high_14 = df['High'].rolling(window=14).max()
    df['Stoch_K'] = 100 * ((df['Close'] - low_14) / (high_14 - low_14))
    df['Stoch_D'] = df['Stoch_K'].rolling(window=3).mean()

    # Returns
    df['Returns'] = df['Close'].pct_change()
    df['Log_Returns'] = np.log(df['Close'] / df['Close'].shift(1))

    # Volatility
    df['Volatility_20'] = df['Returns'].rolling(window=20).std()

    logger.info(f"Calculated technical indicators")

    return df


def resample_data(
    df: pd.DataFrame,
    timeframe: str,
    agg_dict: Optional[Dict] = None
) -> pd.DataFrame:
    """
    Resample data to different timeframe

    Args:
        df: DataFrame with OHLCV data
        timeframe: Target timeframe (e.g., '5T', '1H', '1D')
        agg_dict: Custom aggregation dictionary

    Returns:
        Resampled DataFrame
    """
    if agg_dict is None:
        agg_dict = {
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }

    df_resampled = df.resample(timeframe).agg(agg_dict)
    df_resampled.dropna(inplace=True)

    logger.info(f"Resampled data to {timeframe}: {len(df_resampled)} bars")

    return df_resampled


def split_data(
    df: pd.DataFrame,
    train_ratio: float = 0.7,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15
) -> tuple:
    """
    Split data into train, validation, and test sets

    Args:
        df: DataFrame to split
        train_ratio: Training set ratio
        val_ratio: Validation set ratio
        test_ratio: Test set ratio

    Returns:
        Tuple of (train_df, val_df, test_df)
    """
    assert train_ratio + val_ratio + test_ratio == 1.0, "Ratios must sum to 1.0"

    n = len(df)
    train_size = int(n * train_ratio)
    val_size = int(n * val_ratio)

    train_df = df.iloc[:train_size]
    val_df = df.iloc[train_size:train_size + val_size]
    test_df = df.iloc[train_size + val_size:]

    logger.info(f"Split data: Train={len(train_df)}, Val={len(val_df)}, Test={len(test_df)}")

    return train_df, val_df, test_df


def calculate_metrics(predictions: np.ndarray, actuals: np.ndarray) -> Dict:
    """
    Calculate prediction metrics

    Args:
        predictions: Predicted values
        actuals: Actual values

    Returns:
        Dictionary with metrics
    """
    mse = np.mean((predictions - actuals) ** 2)
    rmse = np.sqrt(mse)
    mae = np.mean(np.abs(predictions - actuals))
    mape = np.mean(np.abs((actuals - predictions) / actuals)) * 100

    # R-squared
    ss_res = np.sum((actuals - predictions) ** 2)
    ss_tot = np.sum((actuals - np.mean(actuals)) ** 2)
    r2 = 1 - (ss_res / ss_tot)

    # Directional accuracy
    direction_pred = np.diff(predictions) > 0
    direction_actual = np.diff(actuals) > 0
    directional_accuracy = np.mean(direction_pred == direction_actual) * 100

    return {
        'mse': float(mse),
        'rmse': float(rmse),
        'mae': float(mae),
        'mape': float(mape),
        'r2': float(r2),
        'directional_accuracy': float(directional_accuracy)
    }


def detect_regime_changes(
    prices: np.ndarray,
    window: int = 50
) -> List[int]:
    """
    Detect regime changes using rolling statistics

    Args:
        prices: Price array
        window: Rolling window size

    Returns:
        List of regime change indices
    """
    # Calculate rolling mean and std
    rolling_mean = pd.Series(prices).rolling(window=window).mean()
    rolling_std = pd.Series(prices).rolling(window=window).std()

    # Z-scores
    z_scores = np.abs((prices - rolling_mean) / rolling_std)

    # Detect significant changes
    threshold = 2.0
    regime_changes = np.where(z_scores > threshold)[0].tolist()

    return regime_changes


def create_features(df: pd.DataFrame, lags: int = 10) -> pd.DataFrame:
    """
    Create lagged features for machine learning

    Args:
        df: DataFrame with OHLCV data
        lags: Number of lags to create

    Returns:
        DataFrame with lagged features
    """
    df = df.copy()

    # Create lagged features
    for i in range(1, lags + 1):
        df[f'Close_lag_{i}'] = df['Close'].shift(i)
        df[f'Returns_lag_{i}'] = df['Returns'].shift(i)
        df[f'Volume_lag_{i}'] = df['Volume'].shift(i)

    # Time features
    if hasattr(df.index, 'hour'):
        df['Hour'] = df.index.hour
        df['DayOfWeek'] = df.index.dayofweek
        df['DayOfMonth'] = df.index.day
        df['Month'] = df.index.month

    # Rolling features
    for window in [5, 10, 20]:
        df[f'Close_rolling_mean_{window}'] = df['Close'].rolling(window=window).mean()
        df[f'Close_rolling_std_{window}'] = df['Close'].rolling(window=window).std()
        df[f'Volume_rolling_mean_{window}'] = df['Volume'].rolling(window=window).mean()

    # Drop NaN rows
    df.dropna(inplace=True)

    logger.info(f"Created {len(df.columns)} features")

    return df


def normalize_data(
    data: np.ndarray,
    method: str = 'standard'
) -> Tuple[np.ndarray, object]:
    """
    Normalize data

    Args:
        data: Data to normalize
        method: Normalization method ('standard', 'minmax')

    Returns:
        Tuple of (normalized_data, scaler)
    """
    from sklearn.preprocessing import StandardScaler, MinMaxScaler

    if method == 'standard':
        scaler = StandardScaler()
    elif method == 'minmax':
        scaler = MinMaxScaler()
    else:
        raise ValueError(f"Unknown method: {method}")

    if len(data.shape) == 1:
        data = data.reshape(-1, 1)

    normalized = scaler.fit_transform(data)

    return normalized, scaler


def save_results(
    results: Dict,
    filename: str,
    output_dir: str = "results/reports"
):
    """
    Save results to JSON file

    Args:
        results: Results dictionary
        filename: Output filename
        output_dir: Output directory
    """
    import json

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    filepath = output_path / filename

    with open(filepath, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    logger.info(f"Results saved to {filepath}")


def load_results(
    filename: str,
    results_dir: str = "results/reports"
) -> Dict:
    """
    Load results from JSON file

    Args:
        filename: Results filename
        results_dir: Results directory

    Returns:
        Results dictionary
    """
    import json

    filepath = Path(results_dir) / filename

    if not filepath.exists():
        logger.error(f"File not found: {filepath}")
        return {}

    with open(filepath, 'r') as f:
        results = json.load(f)

    logger.info(f"Loaded results from {filepath}")

    return results
