# Gold Behavior EA v1 — XAUUSD H1

EA automatique basé sur les **4 recettes LONG** découvertes sur XAUUSD H1 (5 ans de données Deriv MT5) et **validées out-of-sample**.

## 📊 Résultats de l'analyse Python (source)

Base rate long (+2R avant -1R sur 24 bars) = **34.3%**

| Recipe | IS WR | **OOS WR** | Lift OOS | n_OOS |
|---|---|---|---|---|
| **GL1** | `atr_q3 + bb_width_q3 + h_5` | 40.9% | **51.9%** | 1.41 | 104 |
| **GL2** | `bb_width_q3 + dist_ema200_q4 + dist_ema50_q2` | 48.6% | **51.9%** | 1.41 | 54 |
| **GL3** | `dist_ema200_q4 + dist_ema50_q2 + non-London` | 46.4% | **49.3%** | 1.34 | 75 |
| **GL4** | `bb_pos_q2 + bb_width_q3 + rsi_q3` | 42.7% | **47.1%** | 1.28 | 104 |

**Expectancy théorique** à R:R 2:1 :
- GL1/GL2 → +0.55R par trade
- GL3 → +0.48R par trade
- GL4 → +0.41R par trade

**Shorts désactivés** : aucune recette SHORT n'a un OOS WR suffisant pour battre R:R 2:1 (breakeven 33.3%). Meilleur SHORT OOS = 18.8%, insuffisant.

## 🔑 Interprétation des conditions

| Code | Signification |
|---|---|
| `atr_q3` | ATR(14) dans le 3e quartile (50-75% pctile sur 500 bars) = **volatilité modérée-haute** |
| `bb_width_q3` | BB width Q3 = **régime d'expansion de volatilité** (le commun à 3 recettes) |
| `bb_pos_q2` | Prix dans le quart bas-moyen des BB (25-50%) = pullback léger |
| `rsi_q3` | RSI 50-75% pctile = momentum haussier mais pas overbought |
| `dist_ema200_q4` | Prix très au-dessus EMA200 (top 25%) = **macro bullish** (c'est Gold après tout) |
| `dist_ema50_q2` | Prix à distance modérée au-dessus EMA50 = pullback dans la tendance |
| `h_5` | Hours 20-23 UTC = **late US session / overnight Asia open** |
| `!London` | Pas pendant heures London 7-16 UTC |

**Lecture humaine** : l'EA achète Gold quand il est dans une tendance haussière (au-dessus EMA200), en phase d'expansion de volatilité, avec un pullback modéré, souvent en fin de session US ou hors Londres. Du bon swing-momentum classique.

## 🚀 Installation

```
1. MT5 → File → Open Data Folder → MQL5 → Experts → Gold_Behavior_EA_v1.mq5
2. F4 (MetaEditor) → F7 (compile)
3. Strategy Tester (Ctrl+R) :
   - Expert: Gold_Behavior_EA_v1
   - Symbol: XAUUSD
   - Period: H1 (obligatoire)
   - Dates: 2024-01-01 → today  (période OOS — non vue par l'analyse)
   - Model: Every tick based on real ticks (le plus fiable)
   - Initial deposit: 10000 USD
```

## 🔧 Paramètres

- **InpRiskPercent** (1.0%) : % equity risqué par trade
- **InpTPatATR / InpSLatATR** (2.0 / 1.0) : R:R 2:1 — cohérent avec l'entraînement
- **InpMaxSpreadPoints** (50) : ignorer si spread > 50 pts (gold typical 20-40)
- **InpPercentileWindow** (500) : fenêtre rolling pour quartiles (~3 semaines H1)
- **InpEnableGL1/2/3/4** : toggle individuel — teste chaque recette seule pour voir sa contribution
- **InpVerboseLogs** (true) : tous les signaux + contexte dans le Journal MT5
- **InpLogEveryBar** (false) : log chaque bar même sans trade (très verbeux, pour debug)

## 📋 Logs produits dans le Journal MT5

À chaque signal détecté :
```
[SIGNAL] BUY @ 2024-03-15 21:00 | spread=28 | GL1 GL2
  context -> pr[atr=0.58 bbp=0.32 bbw=0.61 de50=0.38 de200=0.78 rsi=0.55]
            flags[atrQ3=1 bbwQ3=1 bbpQ2=1 de200Q4=1 de50Q2=1 rsiQ3=1 h5=1 lon=0]
[OPEN OK] BUY lot=0.35 entry=2185.50 SL=2160.12 TP=2236.26 (ATR=25.38, R:R 2.0:1.0)
```

## 🎯 Attendu au backtest

Sur période OOS (2024-2026) :
- Environ **150-250 trades** total (somme des 4 recettes)
- WR global 42-50% (moyenne pondérée des 4)
- R:R réalisé ≈ 1.85 (après spread/slippage gold)
- Attendu : **PF 1.3-1.8** et **DD < 20%**

**Test recommandé** :
1. Run 1 : toutes recettes activées (baseline)
2. Run 2 : seulement GL1 (la plus simple, 104 trades OOS)
3. Run 3 : GL1 + GL2 (les deux meilleures)
4. Comparer les stats

## ⚠️ Points d'attention

- **Percentile warm-up** : il faut ~3 semaines H1 (500 bars) avant que les quartiles se stabilisent → normal de n'avoir aucun trade au tout début du backtest
- **Server time** : les heures (h_5 = 20-23) sont en **UTC**. Si ton broker affiche en heure locale, les signaux seront décalés. Vérifier avec un `Print(TimeGMT())` au besoin
- **Gold 24/5** : pas de trade pendant les weekends, normal
- **Cooldown 3 bars** : si un trade sort sur un SL, on attend 3 H1 avant de re-ouvrir → évite les retombées immédiates

## 📊 Si le backtest est mauvais

Diagnostic via les logs :
1. Aucun signal ? → `InpLogEveryBar=true` pour voir les percentiles ; vérifier que les quartiles se remplissent bien
2. Beaucoup de signaux mais WR < 40% ? → désactive GL3 et GL4, garde GL1+GL2 (les plus solides)
3. Signaux corrects mais pertes ? → vérifier spread (si > 40 régulièrement, augmenter `InpMaxSpreadPoints` ou ne pas trader cette paire chez ce broker)

Si tout échoue sur Gold → on passe sur **Boom 1000** (plan B, edge structurel déjà prouvé sur indices synthétiques).
