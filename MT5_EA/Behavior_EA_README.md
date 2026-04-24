# Behavior EA v1 — Guide

EA automatique basé sur les **recettes comportementales découvertes** sur EURUSD H1 (5 ans de données) et validées out-of-sample.

## ⚙️ Stratégie

**Entrées** : une position est ouverte dès qu'une des 6 recettes match (OR logique), dans la direction correspondante.

| ID | Recette | Type | WR OOS | Lift |
|---|---|---|---|---|
| L1 | ATR ratio modéré + BB basse + hour 4-7 UTC | LONG | 45.6% | 1.47 |
| L2 | ATR ratio modéré + overlap Lon/NY + 3-4 down en série | LONG | 45.2% | 1.45 |
| L3 | ATR modéré + Lundi + 3-4 down en série | LONG | 41.7% | 1.34 |
| S1 | Jeudi + hour 8-11 UTC + vol expansion court terme | SHORT | 20.9% | **2.52** |
| S2 | Distance EMA200 q3 + Jeudi + hour 8-11 UTC | SHORT | 19.7% | 2.38 |
| S3 | BB width serrée + hour 4-7 UTC + bas du range 20 | SHORT | 18.8% | 2.26 |

**Sortie** : TP = 2×ATR14, SL = 1×ATR14 (R:R 2:1)
**Breakeven WR** : 33.3%. Les 3 longs sont **largement profitables** sur papier. Les shorts ont un WR bas (~20%) mais avec lift ×2.5 vs baseline 9%, donc gains sur les rares events.

## 📦 Installation

```
1. MT5 → File → Open Data Folder → MQL5 → Experts
2. Copie Behavior_EA_v1.mq5
3. F4 (MetaEditor) → F7 (compile)
4. Strategy Tester (Ctrl+R) :
   - Expert: Behavior_EA_v1
   - Symbol: EURUSD
   - Period: H1 obligatoire
   - Date: 2024-01-01 → today (out-of-sample)
   - Modeling: Every tick based on real ticks (ou 1-min OHLC pour rapidité)
```

## 🔧 Paramètres importants

- **InpRiskPercent** (1.0%) : fraction d'equity par trade
- **InpTPatATR / InpSLatATR** (2.0 / 1.0) : R:R 2:1 — cohérent avec l'entraînement
- **InpPercentileWindow** (500) : fenêtre pour les rangs percentiles (≈ 3 semaines H1)
- **InpEnableLong1/2/3, InpEnableShort1/2/3** : désactive recipes individuellement pour tester leur contribution

## 🎯 Pour backtest

**Recommandé** :
1. D'abord test avec toutes recipes activées sur 2024-2026
2. Si bon : désactive les shorts (ils sont plus risqués) → long-only
3. Test comparatif avec chaque recette individuelle activée seule

**Attendu** (sur la base OOS) :
- 100-200 trades/an
- WR global 35-45% (moyenne longs/shorts pondérée)
- PF attendu : 1.3-1.8
- Max DD : 10-20%

## ⚠️ Limites

- Les hours/days sont en UTC (MT5 server time peut différer — à vérifier)
- Les percentiles sont calculés sur une fenêtre glissante de 500 bars — au démarrage du backtest, il faut ~3 semaines de warm-up avant que les recipes soient fiables
- Les recipes SHORT sont plus fragiles (base rate 9%) — considère les désactiver si trop de pertes au début

## 🔬 Prochaines étapes après backtest

- Si profitable : port sur USDJPY et XAUUSD (mêmes recettes peut-être ?)
- Si mauvais sur certaines recettes : affiner les quartiles (q1/q2 frontières)
- Ajouter recipes pour M15/M5 (analyses à re-run)
