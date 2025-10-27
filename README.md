# 🔬 Deriv Synthetic Indices Algorithm Analysis

## 🎯 Objectif du Projet

Reverse-engineering et prédiction des algorithmes des indices synthétiques Deriv (Volatility, Crash, Boom, Step Index) via l'analyse de données historiques et Machine Learning.

## 📐 Méthodologie

### Phase 1 : Extraction de Données
```
MT5 → Python API → Base de données → Preprocessing
```

**Données collectées :**
- OHLCV (Open, High, Low, Close, Volume)
- Tick data (résolution maximale)
- Multiple timeframes (M1, M5, M15, H1, H4, D1)
- Metadata (spreads, timestamps, gaps)

### Phase 2 : Analyse Algorithmique

#### 2.1 Analyse Statistique
- **Distributions** : Identifier si les mouvements suivent des lois normales, exponentielles, etc.
- **Autocorrélation** : Détecter les dépendances temporelles
- **Stationnarité** : Tests ADF, KPSS pour comprendre la nature des séries
- **Volatility clustering** : GARCH, ARCH models
- **Entropy de Shannon** : Mesurer le caractère aléatoire vs déterministe

#### 2.2 Détection de Patterns
- **Spikes artificiels** (Crash/Boom) : fréquence, amplitude, timing
- **Cycles** : FFT (Fast Fourier Transform) pour détecter des périodicités cachées
- **Régularités temporelles** : patterns horaires, journaliers, hebdomadaires
- **Breakpoints** : détection de changements de régime (Step Index)
- **Anomaly detection** : isolation forests, autoencoders

#### 2.3 Analyse Comportementale
- Comportement après spikes
- Réaction à certains niveaux de prix
- Patterns de volume
- Timing des événements (heure, jour de la semaine)
- Mean reversion vs trend following

### Phase 3 : Modélisation & Prédiction

#### 3.1 Approches Classiques
- **ARIMA/SARIMA** : pour les composantes AR, MA
- **GARCH** : pour la volatilité conditionnelle
- **Hidden Markov Models** : pour les états cachés de l'algorithme

#### 3.2 Machine Learning
- **Random Forest / XGBoost** : classification de patterns
- **Support Vector Machines** : pour les régimes de marché
- **Isolation Forest** : pour les anomalies (spikes)

#### 3.3 Deep Learning
- **LSTM (Long Short-Term Memory)** : pour les séquences temporelles
- **GRU (Gated Recurrent Units)** : version optimisée des LSTM
- **Transformers / Attention mechanisms** : pour les dépendances long terme
- **Temporal Convolutional Networks (TCN)** : pour les patterns temporels
- **Autoencoders** : pour la détection d'anomalies et compression de features

#### 3.4 Reinforcement Learning
- **DQN (Deep Q-Network)** : pour l'apprentissage de stratégies
- **PPO (Proximal Policy Optimization)** : pour l'optimisation continue

### Phase 4 : Validation

#### 4.1 Backtesting Rigoureux
- Walk-forward analysis
- Out-of-sample testing
- K-fold cross-validation temporelle
- Monte Carlo simulations

#### 4.2 Métriques de Performance
- **Prédiction** : RMSE, MAE, directional accuracy
- **Trading** : Sharpe ratio, max drawdown, win rate
- **Algorithme** : entropy reduction, pattern recognition accuracy

#### 4.3 Validation de la Compréhension
- ✅ Capacité à prédire les spikes (Crash/Boom)
- ✅ Prédiction de la volatilité future (Volatility indices)
- ✅ Identification des cycles et patterns récurrents
- ✅ Généralisation sur plusieurs indices
- ✅ Performance stable sur données out-of-sample

## 🏗️ Architecture du Projet

```
AlgoIndicesScrap/
├── data/
│   ├── raw/              # Données brutes MT5
│   ├── processed/        # Données nettoyées + features
│   └── models/           # Modèles entraînés sauvegardés
├── src/
│   ├── extractors/       # Extraction depuis MT5
│   ├── analyzers/        # Analyse statistique & patterns
│   ├── models/           # Modèles ML/DL
│   ├── backtesting/      # Système de validation
│   └── utils/            # Utilitaires communs
├── notebooks/            # Jupyter notebooks d'exploration
├── config/               # Fichiers de configuration
├── tests/                # Tests unitaires
├── logs/                 # Logs d'exécution
└── results/              # Résultats, plots, rapports
```

## 🛠️ Stack Technologique

### Core
- **Python 3.10+**
- **MetaTrader5** : API Python pour extraction
- **Pandas / NumPy** : manipulation de données
- **Polars** : alternative ultra-rapide à Pandas

### Analyse Statistique
- **SciPy** : tests statistiques
- **Statsmodels** : ARIMA, GARCH, tests de stationnarité
- **Arch** : modèles GARCH avancés

### Machine Learning
- **Scikit-learn** : modèles classiques
- **XGBoost / LightGBM / CatBoost** : gradient boosting
- **PyTorch / TensorFlow** : deep learning
- **Keras** : interface haut niveau
- **PyTorch Lightning** : training structuré

### Time Series
- **Darts** : framework moderne pour séries temporelles
- **Prophet** : décomposition automatique
- **TSFresh** : feature extraction automatique
- **PyWavelets** : analyse en ondelettes

### Visualisation
- **Plotly** : visualisations interactives
- **Matplotlib / Seaborn** : plots statiques
- **mplfinance** : candlestick charts
- **Dash** : dashboard interactif

### Base de Données
- **SQLite** : stockage local
- **PostgreSQL + TimescaleDB** : pour production
- **HDF5 / Parquet** : stockage efficace de time-series

## 🚀 Quick Start

### 1. Installation
```bash
pip install -r requirements.txt
```

### 2. Configuration
Éditer `config/config.yaml` avec vos paramètres MT5

### 3. Extraction de données
```bash
python src/extractors/mt5_extractor.py --symbol VOLATILITY_10_INDEX --timeframe M1 --days 365
```

### 4. Analyse exploratoire
```bash
jupyter notebook notebooks/01_exploratory_analysis.ipynb
```

### 5. Training d'un modèle
```bash
python src/models/train_lstm.py --config config/model_config.yaml
```

### 6. Backtesting
```bash
python src/backtesting/run_backtest.py --model data/models/lstm_v1.pth --start 2024-01-01 --end 2024-12-31
```

## 📊 Indices à Analyser (Priorités)

### Volatility Indices
- **Volatility 10 Index (1s)** : Volatilité fixe 10%, tick chaque seconde
- **Volatility 25 Index (1s)** : Volatilité fixe 25%
- **Volatility 75 Index (1s)** : Volatilité fixe 75%
- **Volatility 100 Index (1s)** : Volatilité fixe 100%

### Crash/Boom Indices
- **Crash 500 Index** : Chutes soudaines programmées
- **Crash 1000 Index** : Chutes moins fréquentes
- **Boom 500 Index** : Pics soudains programmés
- **Boom 1000 Index** : Pics moins fréquents

### Step Indices
- **Step Index** : Mouvements par paliers fixes

## 🔍 Questions de Recherche Clés

1. **Quelle est la vraie distribution des mouvements ?** (Normal, Student-t, Lévy ?)
2. **Y a-t-il des cycles cachés ?** (FFT, wavelets)
3. **Les spikes Crash/Boom suivent-ils une distribution de Poisson ?**
4. **Les Volatility indices respectent-ils vraiment leur volatilité annoncée ?**
5. **Y a-t-il des patterns horaires/journaliers ?** (market microstructure)
6. **Peut-on détecter les "états" de l'algorithme ?** (HMM)
7. **Les algorithmes ont-ils une "mémoire" ?** (autocorrélation, Hurst exponent)
8. **Y a-t-il du mean reversion systématique ?**

## 📈 Stratégie de Validation

### Critères de Succès
Un algorithme est "compris" si :
- ✅ On peut prédire les propriétés statistiques futures (volatilité, skewness, kurtosis)
- ✅ On peut anticiper les spikes avec >60% de précision
- ✅ On identifie les cycles/patterns avec validation statistique (p < 0.05)
- ✅ Les modèles généralisent sur plusieurs indices de même famille
- ✅ Performance stable sur données out-of-sample (>6 mois)

### Red Flags (Overfitting)
- ⚠️ Performance parfaite sur train, médiocre sur test
- ⚠️ Modèle trop complexe (millions de paramètres)
- ⚠️ Patterns qui disparaissent sur nouvelles données
- ⚠️ Prédictions qui ne battent pas une baseline simple

## 📚 Ressources & Références

- [Deriv API Documentation](https://api.deriv.com/)
- [MT5 Python Documentation](https://www.mql5.com/en/docs/integration/python_metatrader5)
- Time Series Analysis (Box-Jenkins methodology)
- Algorithmic Trading (Ernest Chan, Andreas Clenow)
- Deep Learning for Time Series (N. Laptev, S. Smyl)

## 🤝 Contribution

Ce projet est en développement actif. Les améliorations sont les bienvenues !

## ⚠️ Disclaimer

**Ce projet est à but éducatif et de recherche.**
- Le trading comporte des risques de perte en capital
- Les performances passées ne garantissent pas les performances futures
- Les indices synthétiques sont des instruments complexes
- Ne tradez que de l'argent que vous pouvez vous permettre de perdre

## 📝 License

MIT License - See LICENSE file for details

---

**Last Updated:** 2025-10-27
**Status:** 🚧 En développement actif
