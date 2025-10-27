# Stratégies pour Surmonter la Limitation de 5000 Bougies

## Problème Identifié

L'API Deriv limite les requêtes à **5000 bougies maximum** par appel, quelle que soit la période demandée. Cela affecte notre capacité à entraîner des modèles avec suffisamment de données historiques.

### Impact par Timeframe

| Timeframe | Bougies attendues (365 jours) | Bougies obtenues | Limitation |
|-----------|-------------------------------|------------------|------------|
| M1        | ~525,600                      | 5,000            | ❌ 99% perdu |
| M5        | ~105,120                      | 5,000            | ❌ 95% perdu |
| M15       | ~35,040                       | 5,000            | ❌ 86% perdu |
| H1        | ~8,760                        | 5,000            | ❌ 43% perdu |
| H4        | ~2,190                        | 2,190            | ✅ Complet |
| D1        | ~365                          | 365              | ✅ Complet |

---

## 🎯 Solution 1: Multi-Timeframe (IMPLÉMENTÉE)

### Description
Combiner les données de **M15, H1, et H4** pour donner au modèle à la fois:
- Court terme (M15) - détails intra-journaliers
- Moyen terme (H1) - tendances horaires
- Long terme (H4) - mouvements structurels

### Avantages
✅ Plus de features (contexte multi-échelle)
✅ Capture différents patterns de marché
✅ Améliore la généralisation du modèle
✅ Pas besoin de multiples appels API

### Implémentation
```python
# Déjà implémenté dans notebooks/04_multi_timeframe_lstm.ipynb
# Extrait M15, H1, H4 et les aligne sur H4 comme target
```

### Résultats Attendus
- Amélioration de 2-5% sur la directional accuracy
- Meilleure compréhension du contexte de marché
- Prédictions plus robustes

---

## 🎯 Solution 2: Extraction Multiple et Concaténation

### Description
Faire plusieurs appels API en décalant la période de départ pour obtenir plus de données historiques.

### Implémentation

```python
import asyncio
import pandas as pd
from datetime import datetime, timedelta

async def extract_extended_data(symbol, timeframe, total_days=365):
    """
    Extrait des données en faisant plusieurs appels API
    """
    from src.extractors.deriv_api_extractor import DerivAPIExtractor

    extractor = DerivAPIExtractor()
    all_data = []

    # Calculer combien de batches nécessaires
    # M15: 4 bougies/heure × 24 heures = 96 bougies/jour
    # 5000 bougies ≈ 52 jours pour M15

    if timeframe == 'M15':
        days_per_batch = 50
    elif timeframe == 'H1':
        days_per_batch = 200
    else:
        days_per_batch = total_days  # H4+ ont moins de 5000 bougies

    num_batches = (total_days // days_per_batch) + 1

    for i in range(num_batches):
        start_date = datetime.now() - timedelta(days=total_days - (i * days_per_batch))

        # Appel API pour ce batch
        df = await extractor.extract_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            days=days_per_batch
        )

        if df is not None and len(df) > 0:
            all_data.append(df)

        # Pause pour éviter rate limiting
        await asyncio.sleep(1)

    # Concaténer tous les batches
    if all_data:
        combined_df = pd.concat(all_data)
        combined_df = combined_df.sort_index().drop_duplicates()
        return combined_df

    return None

# Utilisation
df_extended = asyncio.run(extract_extended_data('Volatility 100 Index', 'M15', 365))
print(f"Total candles extracted: {len(df_extended)}")
```

### Avantages
✅ Beaucoup plus de données historiques
✅ Meilleur entraînement du modèle
✅ Capture plus de cycles de marché

### Inconvénients
⚠️ Plusieurs appels API (potentiel rate limiting)
⚠️ Plus long à extraire
⚠️ Possibles doublons à gérer

---

## 🎯 Solution 3: Focus sur H4/D1 (TESTÉE)

### Description
Les timeframes **H4 et D1** ont moins de 5000 bougies sur 365 jours, donc on obtient **toutes les données**.

### Résultats Déjà Testés
| Timeframe | Samples | Directional Accuracy |
|-----------|---------|----------------------|
| M15       | 5,000   | 48.24% ❌            |
| H1        | 5,000   | 50.81% ⚠️            |
| **H4**    | **2,190** | **52.19%** ✅      |

### Analyse
- H4 a montré les **meilleurs résultats** (52.19%)
- Moins de données mais **meilleure qualité de signal**
- Moins de bruit de marché
- Capture mieux les tendances structurelles

### Recommandation
✅ **Utiliser H4 comme timeframe principal**
✅ Ajouter M15 et H1 comme features contextuelles
✅ Augmenter les epochs (200-300) car moins de données

---

## 🎯 Solution 4: Feature Engineering Avancé

### Description
Compenser le manque de données par des **features plus riches**.

### Nouvelles Features à Ajouter

#### 1. Indicateurs Techniques Avancés
```python
# Ichimoku Cloud
conversion_line = (df['High'].rolling(9).max() + df['Low'].rolling(9).min()) / 2
base_line = (df['High'].rolling(26).max() + df['Low'].rolling(26).min()) / 2

# Fibonacci Retracements
recent_high = df['High'].rolling(100).max()
recent_low = df['Low'].rolling(100).min()
fib_0_236 = recent_low + 0.236 * (recent_high - recent_low)
fib_0_382 = recent_low + 0.382 * (recent_high - recent_low)

# Keltner Channels
atr = df['High'] - df['Low']  # Simplified ATR
ema = df['Close'].ewm(span=20).mean()
upper_keltner = ema + 2 * atr
lower_keltner = ema - 2 * atr
```

#### 2. Market Microstructure
```python
# Order Imbalance (si volume disponible)
df['Volume_Imbalance'] = df['Volume'] - df['Volume'].rolling(20).mean()

# Price Action Patterns
df['Higher_High'] = (df['High'] > df['High'].shift(1)).astype(int)
df['Lower_Low'] = (df['Low'] < df['Low'].shift(1)).astype(int)

# Candle Patterns
df['Bullish_Engulfing'] = (
    (df['Close'] > df['Open']) &
    (df['Open'].shift(1) > df['Close'].shift(1)) &
    (df['Close'] > df['Open'].shift(1))
).astype(int)
```

#### 3. Temporal Features
```python
# Heure du jour (algorithmes peuvent avoir des patterns horaires)
df['Hour'] = df.index.hour
df['DayOfWeek'] = df.index.dayofweek

# Cycliques (pour capturer la périodicité)
df['Hour_Sin'] = np.sin(2 * np.pi * df['Hour'] / 24)
df['Hour_Cos'] = np.cos(2 * np.pi * df['Hour'] / 24)
```

#### 4. Lag Features
```python
# Prix passés (autocorrélation)
for lag in [1, 2, 3, 5, 10]:
    df[f'Close_Lag_{lag}'] = df['Close'].shift(lag)
    df[f'Returns_Lag_{lag}'] = df['Returns'].shift(lag)
```

### Avantages
✅ Compense le manque de quantité par la qualité
✅ Capture plus de patterns de marché
✅ Améliore la performance sans données supplémentaires

---

## 🎯 Solution 5: Architectures Avancées

### 1. Attention-LSTM
```python
class AttentionLSTM(nn.Module):
    def __init__(self, input_size, hidden_size=128):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, batch_first=True)

        # Attention mechanism
        self.attention = nn.Linear(hidden_size, 1)

    def forward(self, x):
        lstm_out, _ = self.lstm(x)

        # Calculate attention weights
        attention_weights = torch.softmax(self.attention(lstm_out), dim=1)

        # Weighted sum
        context = torch.sum(attention_weights * lstm_out, dim=1)

        return self.fc(context)
```

**Avantage**: Focus automatiquement sur les timesteps/features importants

### 2. CNN-LSTM Hybrid
```python
class CNN_LSTM(nn.Module):
    def __init__(self, input_size, hidden_size=128):
        super().__init__()

        # CNN pour extraire patterns locaux
        self.conv1 = nn.Conv1d(input_size, 64, kernel_size=3, padding=1)
        self.conv2 = nn.Conv1d(64, 128, kernel_size=3, padding=1)

        # LSTM pour séquences temporelles
        self.lstm = nn.LSTM(128, hidden_size, batch_first=True)

    def forward(self, x):
        # x: (batch, seq_len, features)
        x = x.permute(0, 2, 1)  # (batch, features, seq_len)

        x = F.relu(self.conv1(x))
        x = F.relu(self.conv2(x))

        x = x.permute(0, 2, 1)  # (batch, seq_len, 128)
        lstm_out, _ = self.lstm(x)

        return self.fc(lstm_out[:, -1, :])
```

**Avantage**: CNN capture patterns courts, LSTM capture dépendances longues

### 3. Transformer (State-of-the-Art)
```python
class TimeSeriesTransformer(nn.Module):
    def __init__(self, input_size, d_model=128, nhead=8, num_layers=3):
        super().__init__()

        self.embedding = nn.Linear(input_size, d_model)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=512,
            dropout=0.1
        )

        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers)
        self.fc = nn.Linear(d_model, 1)

    def forward(self, x):
        x = self.embedding(x)
        x = x.permute(1, 0, 2)  # (seq_len, batch, d_model)

        transformer_out = self.transformer(x)

        # Take last timestep
        output = self.fc(transformer_out[-1, :, :])
        return output.squeeze()
```

**Avantage**: Meilleur pour capturer dépendances long-terme

---

## 🎯 Solution 6: Ensemble Methods

### Description
Combiner plusieurs modèles pour améliorer les prédictions.

```python
class EnsemblePredictor:
    def __init__(self):
        self.lstm = MultiTimeframeLSTM(...)
        self.xgboost = XGBRegressor(...)
        self.prophet = Prophet()

    def predict(self, X):
        # Prédictions individuelles
        pred_lstm = self.lstm.predict(X)
        pred_xgb = self.xgboost.predict(X)
        pred_prophet = self.prophet.predict(X)

        # Moyenne pondérée
        weights = [0.5, 0.3, 0.2]  # LSTM, XGBoost, Prophet
        ensemble_pred = (
            weights[0] * pred_lstm +
            weights[1] * pred_xgb +
            weights[2] * pred_prophet
        )

        return ensemble_pred
```

### Avantages
✅ Réduit le variance (overfitting)
✅ Plus robuste aux changements de marché
✅ Capture différents types de patterns

---

## 🎯 Solution 7: Transfer Learning

### Description
Entraîner sur **plusieurs indices** et transférer les connaissances.

```python
# Étape 1: Pre-training sur plusieurs indices
indices = ['Volatility 10', 'Volatility 25', 'Volatility 100', 'Crash 500', 'Boom 500']

for symbol in indices:
    df = load_data(symbol)
    # Entraîner le modèle
    model.train(df)

# Étape 2: Fine-tuning sur l'indice cible
target_symbol = 'Volatility 100 Index'
df_target = load_data(target_symbol)

# Geler les premières couches
for param in model.lstm.parameters():
    param.requires_grad = False

# Fine-tune seulement les dernières couches
model.fc.train(df_target)
```

### Avantages
✅ Utilise plus de données (tous les indices)
✅ Apprend des patterns généraux
✅ Fine-tune sur spécificités de l'indice cible

---

## 📊 Comparaison des Solutions

| Solution | Difficulté | Gain Attendu | Temps Implémentation |
|----------|-----------|--------------|---------------------|
| **Multi-timeframe** ✅ | Facile | +2-5% | Fait |
| Extraction multiple | Moyenne | +5-10% | 2-3 heures |
| Focus H4/D1 | Facile | Testé (52%) | Fait |
| Feature engineering | Moyenne | +3-7% | 3-5 heures |
| Attention-LSTM | Difficile | +5-10% | 1 jour |
| CNN-LSTM | Difficile | +4-8% | 1 jour |
| Transformer | Très difficile | +7-15% | 2-3 jours |
| Ensemble | Moyenne | +5-12% | 1 jour |
| Transfer learning | Difficile | +3-8% | 2 jours |

---

## 🚀 Plan d'Action Recommandé

### Phase 1: Quick Wins (1-2 jours)
1. ✅ **Tester multi-timeframe LSTM** (notebooks/04_multi_timeframe_lstm.ipynb)
2. ⏳ Ajouter feature engineering avancé (Ichimoku, Fibonacci, patterns)
3. ⏳ Essayer extraction multiple pour avoir plus de données M15

### Phase 2: Optimisations (3-5 jours)
4. ⏳ Implémenter Attention-LSTM
5. ⏳ Créer un ensemble LSTM + XGBoost
6. ⏳ Hyperparameter tuning (grid search)

### Phase 3: Advanced (1-2 semaines)
7. ⏳ Implémenter Transformer
8. ⏳ Transfer learning sur tous les indices
9. ⏳ Reinforcement Learning pour trading

### Phase 4: Production (après >55% accuracy)
10. ⏳ Backtesting complet avec coûts de transaction
11. ⏳ Risk management (stop-loss, position sizing)
12. ⏳ Paper trading pendant 1 mois
13. ⏳ Live trading avec capital minimal

---

## 💡 Autres Idées Avancées

### 1. Market Regime Detection
Détecter le régime de marché (trending, ranging, volatile) et utiliser des modèles différents:

```python
def detect_regime(df):
    # Hurst < 0.5 → Mean reverting
    # Hurst > 0.5 → Trending
    # High volatility → Volatile

    if regime == 'mean_reverting':
        return mean_reversion_model.predict(X)
    elif regime == 'trending':
        return trend_following_model.predict(X)
    else:
        return ensemble_model.predict(X)
```

### 2. Online Learning
Mise à jour continue du modèle avec nouvelles données:

```python
# Chaque jour/semaine
new_data = fetch_latest_data()
model.partial_fit(new_data)  # Incremental learning
```

### 3. Multi-Asset Analysis
Analyser corrélations entre indices:

```python
# Volatility 10 vs Volatility 100 peuvent avoir patterns similaires
df_v10 = load_data('Volatility 10')
df_v100 = load_data('Volatility 100')

# Utiliser V10 comme feature pour prédire V100
X['V10_Returns'] = df_v10['Returns']
```

---

## 📈 Objectif Final

**Target**: Directional Accuracy >55% de manière consistante

**Méthodologie**:
1. Implémenter multi-timeframe (fait ✅)
2. Ajouter features avancées
3. Tester architectures avancées
4. Ensemble methods
5. Backtest rigoureux
6. Paper trading
7. Production avec risk management

**Patience et rigueur sont clés pour le trading algorithmique!** 🎯
