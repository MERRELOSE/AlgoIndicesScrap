# Utiliser seulement le prix de clôture ET les indicateurs techniques
print("Calculating technical indicators...")

# Calculer les indicateurs
def calculate_indicators(df):
    df_calc = df.copy()

    # RSI
    delta = df_calc['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df_calc['RSI'] = 100 - (100 / (1 + rs))

    # MACD
    exp1 = df_calc['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df_calc['Close'].ewm(span=26, adjust=False).mean()
    df_calc['MACD'] = exp1 - exp2
    df_calc['MACD_signal'] = df_calc['MACD'].ewm(span=9, adjust=False).mean()

    # Bollinger Bands
    df_calc['BB_middle'] = df_calc['Close'].rolling(window=20).mean()
    bb_std = df_calc['Close'].rolling(window=20).std()
    df_calc['BB_upper'] = df_calc['BB_middle'] + (bb_std * 2)
    df_calc['BB_lower'] = df_calc['BB_middle'] - (bb_std * 2)

    # Moving Averages
    df_calc['SMA_10'] = df_calc['Close'].rolling(window=10).mean()
    df_calc['SMA_20'] = df_calc['Close'].rolling(window=20).mean()
    df_calc['EMA_10'] = df_calc['Close'].ewm(span=10, adjust=False).mean()

    # ATR
    high_low = df_calc['High'] - df_calc['Low']
    high_close = np.abs(df_calc['High'] - df_calc['Close'].shift())
    low_close = np.abs(df_calc['Low'] - df_calc['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df_calc['ATR'] = true_range.rolling(14).mean()

    # Returns
    df_calc['Returns'] = df_calc['Close'].pct_change()

    # Volatility
    df_calc['Volatility'] = df_calc['Returns'].rolling(window=20).std()

    # Drop NaN
    df_calc = df_calc.dropna()

    return df_calc

df_with_indicators = calculate_indicators(df)

print(f"✅ Indicators calculated")
print(f"   Original rows: {len(df)}")
print(f"   After indicators: {len(df_with_indicators)}")

# Features à utiliser
feature_columns = ['Close', 'RSI', 'MACD', 'BB_middle', 'BB_upper', 'BB_lower',
                   'SMA_10', 'SMA_20', 'EMA_10', 'ATR', 'Returns', 'Volatility']

features = df_with_indicators[feature_columns].values

print(f"\n📊 Using {len(feature_columns)} features:")
for i, col in enumerate(feature_columns):
    print(f"   {i+1}. {col}")
