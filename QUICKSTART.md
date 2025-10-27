# 🚀 Guide de Démarrage Rapide

Ce guide vous aidera à démarrer rapidement avec AlgoIndicesScrap pour analyser et prédire les algorithmes des indices synthétiques Deriv.

## 📋 Prérequis

1. **Python 3.10+** installé
2. **MetaTrader 5** installé (PC Windows/Wine sur Linux)
3. **Compte Deriv** (Demo ou Real)
4. **Git** installé

## ⚙️ Installation Rapide

### 1. Cloner le repository (si applicable)

```bash
git clone https://github.com/yourusername/AlgoIndicesScrap.git
cd AlgoIndicesScrap
```

### 2. Configuration automatique

```bash
make quickstart
```

Cette commande va :
- Créer la structure de dossiers
- Installer toutes les dépendances
- Créer le fichier `.env`

### 3. Configuration MT5

Éditer le fichier `.env` avec vos identifiants MT5 :

```bash
nano .env  # ou utilisez votre éditeur préféré
```

Remplir :
```
MT5_LOGIN=votre_numero_compte
MT5_PASSWORD=votre_mot_de_passe
MT5_SERVER=Deriv-Demo
```

## 📊 Utilisation

### Étape 1 : Extraction des données

#### Extraire tous les indices configurés
```bash
make extract
```

#### Extraire un indice spécifique
```bash
python src/extractors/mt5_extractor.py --symbol "Volatility 10 Index" --timeframe M1 --days 365
```

#### Exemples d'indices disponibles
- `Volatility 10 Index`
- `Volatility 25 Index`
- `Volatility 75 Index`
- `Crash 500 Index`
- `Boom 500 Index`

### Étape 2 : Analyse Exploratoire

#### Lancer Jupyter Notebook
```bash
make notebook
```

Ouvrir `notebooks/01_exploratory_analysis.ipynb` et exécuter les cellules.

#### Ou utiliser le script Python directement
```bash
python src/analyzers/statistical_analyzer.py
python src/analyzers/pattern_detector.py
```

### Étape 3 : Entraînement d'un Modèle

```bash
python src/models/lstm_predictor.py
```

### Étape 4 : Backtesting

```bash
python src/backtesting/backtest_engine.py
```

## 📁 Structure du Projet

```
AlgoIndicesScrap/
├── data/
│   ├── raw/              # Données brutes extraites de MT5
│   ├── processed/        # Données prétraitées
│   └── models/           # Modèles entraînés
├── src/
│   ├── extractors/       # Extraction MT5
│   ├── analyzers/        # Analyse statistique
│   ├── models/           # Modèles ML/DL
│   ├── backtesting/      # Système de backtesting
│   └── utils/            # Fonctions utilitaires
├── notebooks/            # Notebooks Jupyter
├── config/               # Configuration
└── results/              # Résultats et graphiques
```

## 🔍 Workflow Typique

### 1. Exploration Initiale

```python
from src.utils.helpers import load_data
from src.analyzers.statistical_analyzer import StatisticalAnalyzer

# Charger les données
df = load_data("Volatility_10_Index", "M1")

# Analyser
analyzer = StatisticalAnalyzer(df)
results = analyzer.full_analysis()

# Vérifier le Hurst exponent
print(f"Hurst: {results['hurst_exponent']['hurst_exponent']:.4f}")
```

### 2. Détection de Patterns

```python
from src.analyzers.pattern_detector import PatternDetector

detector = PatternDetector(df)
patterns = detector.full_pattern_analysis()

# Spikes détectés ?
print(f"Crash spikes: {patterns['spikes']['crash_spikes']['count']}")
```

### 3. Prédiction avec LSTM

```python
from src.models.lstm_predictor import LSTMPredictor

predictor = LSTMPredictor(
    sequence_length=60,
    hidden_size=128
)

train_loader, val_loader, test_loader = predictor.prepare_data(df)
predictor.train(train_loader, val_loader, epochs=100)
results = predictor.evaluate(test_loader)
```

### 4. Backtesting

```python
from src.backtesting.backtest_engine import BacktestEngine

engine = BacktestEngine(
    initial_capital=10000,
    stop_loss=0.02,
    take_profit=0.04
)

engine.run(df, your_strategy_function)
engine.print_summary()
```

## 🎯 Analyses Clés à Faire

### Pour Volatility Indices
1. ✅ Vérifier si la volatilité réelle correspond à la volatilité annoncée
2. ✅ Tester la stationnarité
3. ✅ Calculer le Hurst exponent (mean reversion vs trending)
4. ✅ Chercher des patterns de cycles cachés (FFT)

### Pour Crash/Boom Indices
1. ✅ Détecter et compter les spikes
2. ✅ Analyser la distribution des intervalles entre spikes
3. ✅ Tester si ça suit une distribution de Poisson
4. ✅ Chercher des patterns de timing (heure, jour)

### Pour Step Index
1. ✅ Détecter les change points (ruptures)
2. ✅ Analyser la distribution des tailles de steps
3. ✅ Chercher des patterns de régimes

## 📈 Métriques Importantes

| Métrique | Signification | Interprétation |
|----------|---------------|----------------|
| **Hurst < 0.5** | Mean reverting | Stratégies de retour à la moyenne |
| **Hurst > 0.5** | Trending | Stratégies de suivi de tendance |
| **Hurst ≈ 0.5** | Random walk | Peu de mémoire, difficile à prédire |
| **Entropie basse** | Patterns prévisibles | Bon pour ML |
| **Entropie haute** | Très aléatoire | Difficile à prédire |

## 🛠️ Commandes Utiles

```bash
# Installation
make install              # Installer les dépendances
make install-dev          # + dépendances de développement

# Nettoyage
make clean                # Nettoyer les fichiers temporaires

# Tests
make test                 # Lancer les tests
make lint                 # Vérifier le code
make format               # Formater le code

# Extraction
make extract              # Extraire tous les symboles
make extract-symbol       # Extraire un symbole spécifique

# Analyse
make analyze              # Analyse statistique
make analyze-patterns     # Détection de patterns

# Modèles
make train                # Entraîner LSTM

# Backtesting
make backtest             # Lancer backtest

# Jupyter
make notebook             # Lancer Jupyter
```

## 🔧 Configuration Avancée

### Modifier les indices à analyser

Éditer `config/config.yaml` :

```yaml
symbols:
  volatility:
    - "Volatility 10 Index"
    - "Volatility 25 Index"
  crash:
    - "Crash 500 Index"
```

### Modifier les paramètres du modèle LSTM

Dans `config/config.yaml` :

```yaml
models:
  deep_learning:
    lstm:
      hidden_size: 128
      num_layers: 2
      dropout: 0.2
      sequence_length: 60
```

## 🐛 Dépannage

### Erreur : MT5 initialization failed

**Solution** : Vérifier que :
1. MT5 est bien installé et ouvert
2. Les identifiants dans `.env` sont corrects
3. Le serveur est accessible

### Erreur : Module not found

**Solution** :
```bash
pip install -r requirements.txt
```

### Les données ne se chargent pas

**Solution** :
```bash
# Vérifier que les données existent
ls data/raw/

# Réextraire si nécessaire
make extract
```

## 📚 Ressources

- [Documentation MT5 Python](https://www.mql5.com/en/docs/integration/python_metatrader5)
- [Deriv API Docs](https://api.deriv.com/)
- [Time Series Analysis Guide](https://otexts.com/fpp3/)

## 💡 Prochaines Étapes

Une fois familiarisé avec les bases :

1. **Expérimenter** avec différents modèles (GRU, Transformer, etc.)
2. **Créer** vos propres stratégies de trading
3. **Optimiser** les hyperparamètres
4. **Tester** sur données out-of-sample
5. **Déployer** en production (avec prudence !)

## ⚠️ Avertissements

- ⚠️ **Trading à risque** : Ne tradez que l'argent que vous pouvez perdre
- ⚠️ **Backtesting ≠ Garantie** : Les performances passées ne garantissent pas les performances futures
- ⚠️ **Commencez en DEMO** : Testez toujours en compte démo d'abord
- ⚠️ **Gestion du risque** : Utilisez toujours stop-loss et position sizing

## 🤝 Support

En cas de problème :
1. Vérifier la documentation
2. Consulter les issues GitHub
3. Créer une nouvelle issue avec détails

---

**Bon trading et bonne analyse ! 🚀📊**
