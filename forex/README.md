# Forex/Gold Behavioral Analysis

Pipeline d'analyse comportementale pour identifier les contextes qui précèdent les gros mouvements (long ou short) et en tirer des recettes de trading validées out-of-sample.

## Structure actuelle

```
forex/
├── config/forex_config.yaml     # Config MT5 / features (legacy mais gardée)
├── data/raw/                    # Parquet MT5 (cache automatique)
├── src/
│   ├── extractor.py             # Extraction massive MT5 via Python API
│   ├── features.py              # ATR et utilitaires
│   └── behavior/
│       ├── events.py            # Détection "big moves" (triple-barrier)
│       ├── context.py           # Features binnées par percentile
│       └── recipes.py           # Discovery de combinaisons + OOS validation
├── reports/                     # CSV des recettes par actif/TF/direction
└── run_behavior.py              # ⭐ Orchestration
```

## Usage

```bash
# Analyse swing H1 sur 5 ans
python forex/run_behavior.py --pair XAUUSD --timeframe H1 --years 5

# Analyse scalping M15
python forex/run_behavior.py --pair XAUUSD --timeframe M15 --years 2 --scalping

# Paramètres utiles
#   --min-lift 1.15    : seuil de lift pour garder une recette
#   --top-k 20         : nombre de recettes à afficher par direction
#   --overwrite        : force re-extraction des données MT5
```

## Output

Pour chaque run, on obtient :
- Top recettes LONG (conditions qui précèdent un +2R avant -1R)
- Top recettes SHORT (conditions qui précèdent un -2R avant +1R) — **patterns de faiblesse**
- Validation out-of-sample (70/30 split temporel)
- Base rates du marché pour calibrer les attentes

## Projet cible

**Gold (XAUUSD) H1** : la volatilité et le spread favorable (ATR ~20-40 pips, spread 2-3 pips) rendent le R:R réel beaucoup plus proche du théorique que sur EURUSD. Si l'analyse dégage des recettes avec lift OOS ≥ 1.4 et WR suffisant pour battre le R:R effectif, on bâtit un EA.

**Plan B** : si le gold ne donne pas d'edge exploitable, retour sur les **indices synthétiques Deriv** (Boom 1000, Crash 1000) où l'edge structurel est déjà prouvé (voir `behavior_discovery.py` et `CrashHunter_v6.mq5` à la racine du projet).
