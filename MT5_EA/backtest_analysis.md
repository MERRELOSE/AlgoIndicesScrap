# Backtest Analysis & Cleanup Plan
> Date: 2026-04-16 | Capital: $200 | Period: Jan 2024 - Apr 2026

---

## CRASH 1000 INDEX

**Global**: $200 -> $4923 | 950 trades | WR 47.6% | PF 1.61 | Max DD $302 | 25/28 mois profit (89%)

### Signals RENTABLES (a garder)

| Signal | Trades | WR | PnL | Avg/trade |
|---|---|---|---|---|
| squeeze_up+h4 | 298 | 47% | +$1489 | $5.00 |
| squeeze_up | 197 | 51% | +$994 | $5.05 |
| rsi_momentum+h4 | 151 | 45% | +$764 | $5.06 |
| rsi_os+consec_rev+h4 | 37 | 59% | +$629 | $17.00 |
| rsi_os+consec_rev | 55 | 47% | +$276 | $5.02 |
| rsi_os+consec_rev+overext | 21 | 43% | +$147 | $7.01 |
| rsi_os+overext+post_crash+h4 | 7 | 71% | +$138 | $19.69 |
| rsi_os+post_crash+h4 | 10 | 70% | +$117 | $11.69 |
| rsi_os+consec_rev+overext+h4 | 15 | 47% | +$108 | $7.22 |
| rsi_os+overext | 11 | 55% | +$105 | $9.55 |
| rsi_os+overext+post_crash | 6 | 50% | +$29 | $4.86 |
| squeeze_up+rsi_momentum+h4 | 28 | 39% | +$15 | $0.55 |
| rsi_os+consec_rev+post_crash | 2 | 50% | +$8 | $3.91 |

### Signals A VIRER (PnL negatif)

| Signal | Trades | WR | PnL | Avg/trade | Action |
|---|---|---|---|---|---|
| squeeze_up+cross+h4 | 51 | 43% | -$3 | -$0.06 | REMOVE: cross pollue le squeeze |
| squeeze_up+consec_rev | 6 | 67% | -$4 | -$0.74 | REMOVE: trop peu de trades, instable |
| rsi_os+consec_rev+overext+post_crash | 10 | 40% | -$5 | -$0.53 | REMOVE: trop de confluence = signal tardif |
| squeeze_up+consec_rev+h4 | 36 | 31% | -$6 | -$0.17 | REMOVE: WR 31% trop faible |
| consec_rev+overext+post_crash+h4 | 1 | 0% | -$18 | -$17.62 | REMOVE: 1 seul trade, pas fiable |
| rsi_os+post_crash | 8 | 50% | -$65 | -$8.08 | REMOVE: post_crash sans h4 = dangereux |

### Cleanup prevu

- **Impact**: -112 trades, +$101 PnL net -> ~$4820 sur 838 trades
- **Solution 1**: Desactiver `cross` quand squeeze_up est actif (evite squeeze_up+cross+h4)
- **Solution 2**: Exiger h4 pour post_crash (evite rsi_os+post_crash sans h4)
- **Solution 3**: Bloquer consec_rev quand squeeze_up est deja actif (evite squeeze_up+consec_rev combos)
- **Solution 4**: Limiter max 3 signaux simultanes (evite les combos 4+ qui arrivent trop tard)

---

## CRASH 500 INDEX

**Global**: $200 -> $836 | 528 trades | WR 40.7% | PF 1.25 | Max DD $253 | 16/28 mois profit (57%)
**Verdict**: FRAGILE - PF trop bas, loss streak 12, DD > 50% du peak

### Signals RENTABLES (a garder)

| Signal | Trades | WR | PnL | Avg/trade |
|---|---|---|---|---|
| ema_cross+h4 | 186 | 41% | +$349 | $1.88 |
| post_crash+h4 | 48 | 54% | +$197 | $4.09 |
| consec_rev+rsi_mom+h4 | 4 | 75% | +$56 | $14.01 |
| post_crash+rsi_os+overext+consec | 6 | 33% | +$54 | $8.99 |
| rsi_os+overext+consec_rev+h4 | 7 | 43% | +$49 | $6.96 |
| rsi_os+overext | 10 | 50% | +$37 | $3.69 |
| rsi_os+consec_rev | 59 | 36% | +$24 | $0.40 |
| post_crash+rsi_mom+h4 | 1 | 100% | +$9 | $8.60 |

### Signals A VIRER (PnL negatif)

| Signal | Trades | WR | PnL | Avg/trade | Action |
|---|---|---|---|---|---|
| squeeze_up+consec_rev+h4 | 48 | 38% | -$49 | -$1.02 | REMOVE: squeeze+consec = mauvais combo |
| squeeze_up+rsi_mom+h4 | 92 | 37% | -$30 | -$0.32 | REMOVE: gros volume, petit edge negatif |
| post_crash+rsi_os+h4 | 5 | 20% | -$23 | -$4.62 | REMOVE: WR 20% catastrophique |
| post_crash+consec_rev+h4 | 6 | 50% | -$19 | -$3.08 | REMOVE: post_crash+consec = trop tardif |
| ema_cross+squeeze_up+h4 | 53 | 40% | -$16 | -$0.30 | REMOVE: squeeze pollue le cross |
| rsi_os+overext+h4 | 3 | 33% | -$1 | -$0.26 | REMOVE: trop peu de trades |

### Cleanup prevu

- **Impact**: -207 trades, +$137 PnL net -> ~$773 sur 321 trades
- **Solution 1**: Desactiver squeeze_up entierement sur C500 (squeeze_up contribue -$95 total sur C500)
- **Solution 2**: post_crash seul +h4 = bon (+$197), mais post_crash+rsi_os ou +consec = mauvais -> bloquer combos post_crash
- **Solution 3**: Garder seulement ema_cross+h4 et post_crash+h4 comme signals principaux
- **Attention**: Meme apres cleanup, C500 reste marginal (PF ~1.4 estime). A surveiller en demo avant live

---

## CRASH 900 INDEX

**Global**: $200 -> $7560 | 474 trades | WR 48.7% | PF 1.60 | Max DD $611 | 17/20 mois profit (85%)
**Verdict**: MEILLEUR EA - $15.53/trade expectancy, loss streak max 6, TP continuation analyse OK
**Data**: commence Sept 2024 (20 mois seulement)

### Signals RENTABLES (a garder)

| Signal | Trades | WR | PnL | Avg/trade |
|---|---|---|---|---|
| squeeze_up+h4 | 219 | 48% | +$3419 | $15.61 |
| squeeze_up | 92 | 46% | +$1393 | $15.15 |
| rsi_momentum+h4 | 73 | 48% | +$1255 | $17.19 |
| rsi_os+overext | 8 | 75% | +$411 | $51.38 |
| rsi_os+consec_rev | 35 | 51% | +$325 | $9.30 |
| rsi_os+consec_rev+h4 | 23 | 52% | +$213 | $9.24 |
| rsi_os+overext+post_crash+h4 | 4 | 50% | +$178 | $44.52 |
| rsi_os+consec_rev+overext | 4 | 50% | +$127 | $31.83 |
| rsi_momentum+consec_rev+h4 | 2 | 50% | +$98 | $49.14 |
| overext+post_crash+h4 | 2 | 100% | +$73 | $36.38 |
| rsi_os+consec_rev+post_crash | 3 | 33% | +$23 | $7.60 |

### Signals A VIRER (PnL negatif)

| Signal | Trades | WR | PnL | Avg/trade | Action |
|---|---|---|---|---|---|
| rsi_os+consec_rev+overext+post_crash | 7 | 57% | -$91 | -$12.98 | REMOVE: combo 4+ = trop tardif, gros avg loss |
| overext+post_crash | 1 | 0% | -$40 | -$40.27 | REMOVE: 1 trade, post_crash sans h4 |
| rsi_os+post_crash+h4 | 1 | 0% | -$25 | -$24.63 | REMOVE: 1 trade, pas fiable |

### Diagnostics avances

**Big losses (>2x avg)**: 17 trades = -$2019
- 10/17 sont squeeze_up+h4 -> normal car c'est le signal le plus frequent
- Sans ces big losses: profit serait $9379

**Meilleures heures**: 02:00 (55.6%), 16:00 (60.9%), 19:00 (64.3%)
**Pires heures**: 08:00 (39.4%), 09:00 (41.7%)
**Meilleur jour**: Mercredi (61.1% WR)
**Pires jours**: Jeudi (41.3%), Vendredi (40.8%)

**TP continuation**: apres TP, prix monte en moyenne +0.80 ATR de plus -> TP 3.0 ATR est bien calibre

### Cleanup prevu

- **Impact**: -9 trades, +$156 PnL net -> impact minimal, deja tres propre
- **Solution 1**: Bloquer combos 4+ signaux (evite rsi_os+consec_rev+overext+post_crash)
- **Solution 2**: Exiger h4 pour post_crash (evite overext+post_crash seul)
- **Option avancee**: Filtrer heures 08-09 (WR <42%) et jours Jeu/Ven (WR ~41%) -> reduirait trades de ~30% mais augmenterait WR

---

## COMPARATIF DES 3 INDEX (AVANT vs APRES CLEANUP v5.2)

### AVANT cleanup
| Metrique | C1000 | C500 | C900 |
|---|---|---|---|
| Return | 2359% | 318% | 3824% |
| PF | 1.61 | 1.25 | 1.49 |
| WR | 47.6% | 40.7% | 46.6% |
| Trades | 950 | 528 | 650 |
| Avg/trade | $4.97 | $1.21 | $11.77 |
| Max DD | $302 | $253 | $777 |
| Mois profit | 89% | 57% | 85% |
| Loss streak | 8 | 12 | 8 |

### APRES cleanup v5.2
| Metrique | C1000 | C500 | C900 | Delta moyen |
|---|---|---|---|---|
| Return | **2429%** | **703%** | **3944%** | +773% |
| PF | **1.68** | **1.48** | **1.52** | **+0.11** |
| WR | **48.2%** | **42.3%** | **46.7%** | +1.0% |
| Trades | 894 | 333 | 627 | -92 |
| Avg/trade | **$5.43** | **$4.22** | **$12.58** | +$1.76 |
| Max DD | $358 | **$234** | **$685** | - |
| Mois profit | 89% | **64%** | **90%** | +4% |
| Loss streak | **7** | **8** | 8 | -2.3 |
| Signals perdants | 1 | **0** | 1 | -4 |

**Signals rentables partout** (core signals a garder):
- squeeze_up (+h4) : TOP sur C1000 et C900, PERDANT sur C500
- rsi_os+consec_rev (+h4) : profitable partout
- rsi_os+overext : profitable partout
- post_crash+h4 : profitable partout

**Signals problematiques partout** (a virer sur les 3):
- Combos 4+ signaux (trop tardifs, gros losses)
- post_crash sans h4 (dangereux)
- squeeze+consec_rev (mauvais combo)

**Conclusion**:
- C900 = champion ($15.53/trade, meilleur ratio)
- C1000 = solide ($4.97/trade, plus de volume)
- C500 = fragile (PF 1.25, a surveiller ou retirer)

## PLAN D'ACTION GLOBAL
1. [x] Backtest C1000 -> analyser signals
2. [x] Backtest C500 -> analyser signals (FRAGILE, PF 1.25)
3. [x] Backtest C900 -> analyser signals (CHAMPION)
4. [x] Comparer les 3: quels signals sont rentables partout vs specifiques
5. [x] Appliquer le cleanup dans les EA (v5.2 blocks ajoutes)
6. [x] Re-backtest valide: C1000 +$134, C500 +$769, C900 +$239
7. [ ] Deployer en demo

## NOTE C900: v5 > v5.1
Le v5 C900 ($7848, 650 trades) est meilleur que v5.1 ($7560, 474 trades).
v5.1 bloquait trop agressivement. On travaille sur v5 + nouveaux blocks cibles = v5.2.
