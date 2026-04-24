//+------------------------------------------------------------------+
//|                     ForexSessionsPro_EA_v1.mq5                   |
//|                     Port du Pine Script v2                        |
//|                     AlgoIndicesScrap Project                      |
//+------------------------------------------------------------------+
//  Strategies (v2 logic, toutes les options togglables pour backtest):
//    1. Asian Breakout (avec retest optionnel)
//    2. VWAP Bounce (SL serré 0.7 ATR)
//    3. Kill Zone Entries (London 08-11 / NY 13-16 UTC)
//
//  Filtres (on/off via inputs pour comparer les configs):
//    - HTF trend filter (H4 EMA50)
//    - Range size filter (0.8-3.0 x ATR)
//    - KZ freshness (30 min par défaut)
//    - Cooldown bars après signal
//    - Priorité KZ > BO > VWAP
//
//  LOGS : tout est imprimé dans le journal Expert via Print/PrintFormat
//  ([SIGNAL] / [SKIP] / [OPEN OK] / [OPEN FAIL]). Active
//  InpVerboseContext pour ajouter les flags filtre à chaque ligne.
//
//  TIMEFRAME CIBLE : M15 (calibrage Pine v2). Autres TFs : ré-ajuster.
//+------------------------------------------------------------------+
#property copyright "AlgoIndicesScrap"
#property version   "1.00"
#property description "Port MT5 du Forex Sessions PRO v2 — 3 strategies, logs journal uniquement."
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//+------------------------------------------------------------------+
//| INPUTS                                                            |
//+------------------------------------------------------------------+
input group "=== Risk ==="
input double InpRiskPercent       = 1.0;    // % equity par trade
input double InpFixedLot          = 0.0;    // 0 = risk-based
input int    InpMaxSpreadPoints   = 30;     // skip si spread > ce seuil
input int    InpMaxPositions      = 1;
input int    InpMagic             = 780020;

input group "=== Timezone ==="
input int    InpServerGMTOffsetHours = 0;   // broker server -> UTC

input group "=== Sessions (heures UTC) ==="
input int    InpTokyoStart        = 0;
input int    InpTokyoEnd          = 9;
input int    InpLondonStart       = 7;
input int    InpLondonEnd         = 16;
input int    InpNYStart           = 13;
input int    InpNYEnd             = 22;
input int    InpLondonKZStart     = 8;
input int    InpLondonKZEnd       = 11;
input int    InpNYKZStart         = 13;
input int    InpNYKZEnd           = 16;

input group "=== Stratégies ==="
input bool   InpEnableAsianBO     = true;
input bool   InpEnableVWAP        = true;
input bool   InpEnableKZ          = true;
input bool   InpPriorityMode      = true;   // 1 signal/bar : KZ > BO > VWAP

input group "=== Asian Breakout Options ==="
input bool   InpRequireRetest     = true;
input int    InpMaxRetestBars     = 8;
input double InpRetestToleranceATR= 0.3;
input double InpRangeMinATRRatio  = 2.0;   // v1.1: range Asie vs ATR(14) M15 typique = 5-15
input double InpRangeMaxATRRatio  = 15.0;

input group "=== KZ Freshness ==="
input bool   InpKZFreshOnly       = true;
input int    InpKZFreshMinutes    = 30;

input group "=== HTF Trend Filter ==="
input bool             InpUseHTFTrend    = true;
input ENUM_TIMEFRAMES  InpHTFTimeframe   = PERIOD_H4;
input int              InpHTFEMAPeriod   = 50;

input group "=== Indicateurs ==="
input int    InpATRPeriod         = 14;
input int    InpEMAPeriod         = 9;
input int    InpVolMAPeriod       = 20;

input group "=== Risk par stratégie ==="
input double InpATR_SL_VWAP       = 0.7;    // mult ATR pour VWAP Bounce SL
input double InpATR_SL_KZ         = 1.5;    // mult ATR pour KZ SL
input double InpDefaultRR         = 2.5;   // v1.1

input group "=== Filtres qualité ==="
input int    InpMinQuality        = 60;
input bool   InpVolumeFilter      = true;
input bool   InpLocalTrendFilter  = true;

input group "=== Trade Management ==="
input int    InpCooldownBars      = 5;      // bougies muettes après signal

input group "=== Logging ==="
input bool   InpPrintSummary      = true;
input bool   InpLogSkips          = true;   // [SKIP] chaque fois qu'un filtre rejette
input bool   InpLogSessionEvents  = true;   // [SESSION]/[RANGE]/[KZ] transitions
input bool   InpLogEveryBar       = false;  // [BAR] snapshot à chaque bougie (très verbeux)
input int    InpHeartbeatBars     = 96;     // [HB] rappel périodique (96 bars M15 = 1 jour)
input bool   InpVerboseContext    = false;  // ajoute les flags filtre sur les lignes SIGNAL/SKIP

//+------------------------------------------------------------------+
//| GLOBALS                                                           |
//+------------------------------------------------------------------+
CTrade         g_trade;
CPositionInfo  g_pos;

int g_atr_handle     = INVALID_HANDLE;
int g_ema9_handle    = INVALID_HANDLE;
int g_htf_ema_handle = INVALID_HANDLE;

datetime g_last_bar = 0;
int      g_last_signal_bar_idx = -9999;  // bar absolu index au moment du dernier signal

// Asian range state
double   g_asian_high          = 0;
double   g_asian_low           = 0;
bool     g_asian_range_valid   = false;
bool     g_asian_broken_up     = false;
bool     g_asian_broken_down   = false;
int      g_broken_bar_up_idx   = -1;
int      g_broken_bar_down_idx = -1;
bool     g_long_taken          = false;
bool     g_short_taken         = false;
bool     g_prev_in_tyo         = false;

// KZ freshness
datetime g_london_kz_start_utc = 0;
datetime g_ny_kz_start_utc     = 0;
bool     g_prev_in_london_kz   = false;
bool     g_prev_in_ny_kz       = false;

// VWAP daily
double   g_vwap_cum_tpv  = 0;
double   g_vwap_cum_vol  = 0;
datetime g_vwap_day      = 0;

// Bar counter (pour heartbeat)
int g_bars_processed = 0;

// --- Diagnostic counters (tous imprimés en DEINIT) ---
int g_bars_tyo = 0, g_bars_ldn = 0, g_bars_ny = 0;
int g_bars_lkz = 0, g_bars_nkz = 0, g_bars_fresh_kz = 0;

int g_ranges_captured = 0;
int g_ranges_validated = 0;
int g_ranges_rejected_size = 0;

// BO
int g_bo_potential_long = 0, g_bo_potential_short = 0;
int g_bo_skipped_taken = 0, g_bo_skipped_htf = 0, g_bo_skipped_no_break = 0, g_bo_skipped_no_retest = 0;

// VWAP
int g_vwap_crossovers_long = 0, g_vwap_crossovers_short = 0;
int g_vwap_skipped_far = 0, g_vwap_skipped_htf = 0, g_vwap_skipped_trend = 0, g_vwap_skipped_vol = 0;

// KZ
int g_kz_crossovers_long = 0, g_kz_crossovers_short = 0;
int g_kz_skipped_htf = 0, g_kz_skipped_vol = 0, g_kz_skipped_not_fresh = 0;

// Signaux finaux
int g_signals_taken  = 0;
int g_signals_bo     = 0;
int g_signals_vwap   = 0;
int g_signals_kz     = 0;
int g_signals_skipped_quality = 0;
int g_signals_skipped_cooldown = 0;
int g_signals_skipped_htf = 0;

//+------------------------------------------------------------------+
//| INIT                                                              |
//+------------------------------------------------------------------+
int OnInit()
{
   if(_Period != PERIOD_M15)
      PrintFormat("⚠ ForexSessionsPro_EA calibré pour M15. TF actuel : %s", EnumToString(_Period));

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_trade.SetMarginMode();
   g_trade.SetDeviationInPoints(20);

   g_atr_handle     = iATR(_Symbol, PERIOD_CURRENT, InpATRPeriod);
   g_ema9_handle    = iMA(_Symbol, PERIOD_CURRENT, InpEMAPeriod, 0, MODE_EMA, PRICE_CLOSE);
   g_htf_ema_handle = iMA(_Symbol, InpHTFTimeframe, InpHTFEMAPeriod, 0, MODE_EMA, PRICE_CLOSE);

   if(g_atr_handle == INVALID_HANDLE || g_ema9_handle == INVALID_HANDLE || g_htf_ema_handle == INVALID_HANDLE)
   {
      Print("ERROR: Failed to init indicator handles");
      return INIT_FAILED;
   }

   PrintFormat("=== ForexSessionsPro_EA v1.00 init ===");
   PrintFormat("  Symbol=%s TF=%s Magic=%d", _Symbol, EnumToString(_Period), InpMagic);
   PrintFormat("  Server→UTC offset=%d h", InpServerGMTOffsetHours);
   PrintFormat("  Sessions UTC: Tokyo=%d-%d Londres=%d-%d NY=%d-%d",
               InpTokyoStart, InpTokyoEnd, InpLondonStart, InpLondonEnd, InpNYStart, InpNYEnd);
   PrintFormat("  KZ UTC: London=%d-%d NY=%d-%d  | fresh=%s %dmin",
               InpLondonKZStart, InpLondonKZEnd, InpNYKZStart, InpNYKZEnd,
               InpKZFreshOnly ? "Y" : "N", InpKZFreshMinutes);
   PrintFormat("  Strategies: BO=%s VWAP=%s KZ=%s | priority=%s",
               InpEnableAsianBO ? "Y" : "N", InpEnableVWAP ? "Y" : "N",
               InpEnableKZ ? "Y" : "N", InpPriorityMode ? "Y" : "N");
   PrintFormat("  BO: retest=%s max_bars=%d range=[%.1f,%.1f] ATR",
               InpRequireRetest ? "Y" : "N", InpMaxRetestBars,
               InpRangeMinATRRatio, InpRangeMaxATRRatio);
   PrintFormat("  HTF filter: %s %s EMA%d",
               InpUseHTFTrend ? "ON" : "OFF", EnumToString(InpHTFTimeframe), InpHTFEMAPeriod);
   PrintFormat("  Risk=%.2f%% | RR=%.1f | SL: VWAP=%.1fATR KZ=%.1fATR",
               InpRiskPercent, InpDefaultRR, InpATR_SL_VWAP, InpATR_SL_KZ);
   PrintFormat("  Cooldown=%d bars | MinQuality=%d%%", InpCooldownBars, InpMinQuality);

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| DEINIT                                                            |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_atr_handle     != INVALID_HANDLE) IndicatorRelease(g_atr_handle);
   if(g_ema9_handle    != INVALID_HANDLE) IndicatorRelease(g_ema9_handle);
   if(g_htf_ema_handle != INVALID_HANDLE) IndicatorRelease(g_htf_ema_handle);

   if(InpPrintSummary && MQLInfoInteger(MQL_TESTER))
      PrintDiagnosticSummary();
}

//+------------------------------------------------------------------+
//| DIAGNOSTIC SUMMARY (style WeekendGap)                             |
//+------------------------------------------------------------------+
void PrintDiagnosticSummary()
{
   Print("======================================================================");
   Print("  FOREX SESSIONS PRO EA v1 - DIAGNOSTIC COUNTERS");
   Print("======================================================================");
   Print("  Bars processed:         ", g_bars_processed);
   Print("    in Tokyo:             ", g_bars_tyo);
   Print("    in London:            ", g_bars_ldn);
   Print("    in New York:          ", g_bars_ny);
   Print("    in London KZ:         ", g_bars_lkz);
   Print("    in NY KZ:             ", g_bars_nkz);
   Print("    in Fresh KZ:          ", g_bars_fresh_kz);
   Print("");
   Print("  Asian ranges captured:  ", g_ranges_captured);
   Print("    validated (size OK):  ", g_ranges_validated);
   Print("    rejected (size):      ", g_ranges_rejected_size);
   Print("");
   Print("  --- ASIAN BREAKOUT ---");
   Print("    potential LONG:       ", g_bo_potential_long);
   Print("    potential SHORT:      ", g_bo_potential_short);
   Print("    skipped - long/short already taken: ", g_bo_skipped_taken);
   Print("    skipped - HTF filter:               ", g_bo_skipped_htf);
   Print("    skipped - no break yet:             ", g_bo_skipped_no_break);
   Print("    skipped - retest not valid:         ", g_bo_skipped_no_retest);
   Print("");
   Print("  --- VWAP BOUNCE ---");
   Print("    crossover LONG detected:  ", g_vwap_crossovers_long);
   Print("    crossover SHORT detected: ", g_vwap_crossovers_short);
   Print("    skipped - too far from VWAP: ", g_vwap_skipped_far);
   Print("    skipped - HTF filter:        ", g_vwap_skipped_htf);
   Print("    skipped - local trend EMA9:  ", g_vwap_skipped_trend);
   Print("    skipped - volume filter:     ", g_vwap_skipped_vol);
   Print("");
   Print("  --- KILL ZONE ---");
   Print("    crossover LONG (vs EMA9):  ", g_kz_crossovers_long);
   Print("    crossover SHORT (vs EMA9): ", g_kz_crossovers_short);
   Print("    skipped - not fresh:     ", g_kz_skipped_not_fresh);
   Print("    skipped - HTF filter:    ", g_kz_skipped_htf);
   Print("    skipped - volume filter: ", g_kz_skipped_vol);
   Print("");
   Print("  --- FINAL DISPATCH ---");
   Print("    Signals TAKEN:        ", g_signals_taken,
         "  (BO=", g_signals_bo, " VWAP=", g_signals_vwap, " KZ=", g_signals_kz, ")");
   Print("    Skipped - quality:    ", g_signals_skipped_quality);
   Print("    Skipped - cooldown:   ", g_signals_skipped_cooldown);
   Print("    Skipped - HTF dispatch: ", g_signals_skipped_htf);
   Print("");
   PrintPerStrategyPerformance();
   Print("======================================================================");
   Print("  Tip: si 'Bars in Tokyo'=0 -> InpServerGMTOffsetHours probablement faux.");
   Print("  Tip: si 'potential LONG/SHORT' BO = 0 -> aucun crossover pendant Londres,");
   Print("       vérifier range asiatique + taille range.");
   Print("======================================================================");
}

//+------------------------------------------------------------------+
//| Performance ventilée par stratégie (parse commentaire du deal)    |
//+------------------------------------------------------------------+
void PrintPerStrategyPerformance()
{
   if(!HistorySelect(0, TimeCurrent()))
   {
      Print("  --- PERFORMANCE BY STRATEGY --- (history select failed)");
      return;
   }

   int total = HistoryDealsTotal();
   ulong  open_pids[];
   string open_cmts[];

   // Pass 1 : collecter les OPEN deals (commentaire = stratégie)
   for(int i = 0; i < total; i++)
   {
      ulong t = HistoryDealGetTicket(i);
      if(HistoryDealGetInteger(t, DEAL_MAGIC) != InpMagic) continue;
      if(HistoryDealGetInteger(t, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
      long pid = HistoryDealGetInteger(t, DEAL_POSITION_ID);
      int n = ArraySize(open_pids);
      ArrayResize(open_pids, n + 1);
      ArrayResize(open_cmts, n + 1);
      open_pids[n] = (ulong)pid;
      open_cmts[n] = HistoryDealGetString(t, DEAL_COMMENT);
   }

   // Pass 2 : aggréger les CLOSE deals par stratégie
   double pnl_bo = 0, pnl_vwap = 0, pnl_kz = 0;
   int    n_bo = 0, n_vwap = 0, n_kz = 0;
   int    w_bo = 0, w_vwap = 0, w_kz = 0;

   for(int i = 0; i < total; i++)
   {
      ulong t = HistoryDealGetTicket(i);
      if(HistoryDealGetInteger(t, DEAL_MAGIC) != InpMagic) continue;
      if(HistoryDealGetInteger(t, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;

      ulong pid = (ulong)HistoryDealGetInteger(t, DEAL_POSITION_ID);
      double pnl = HistoryDealGetDouble(t, DEAL_PROFIT)
                 + HistoryDealGetDouble(t, DEAL_SWAP)
                 + HistoryDealGetDouble(t, DEAL_COMMISSION);

      string strategy = "";
      for(int k = 0; k < ArraySize(open_pids); k++)
         if(open_pids[k] == pid) { strategy = open_cmts[k]; break; }

      if(StringFind(strategy, "BO")   == 0) { pnl_bo   += pnl; n_bo++;   if(pnl > 0) w_bo++; }
      else if(StringFind(strategy, "VWAP") == 0) { pnl_vwap += pnl; n_vwap++; if(pnl > 0) w_vwap++; }
      else if(StringFind(strategy, "KZ")   == 0) { pnl_kz   += pnl; n_kz++;   if(pnl > 0) w_kz++; }
   }

   Print("  --- PERFORMANCE BY STRATEGY ---");
   if(n_bo > 0)
      PrintFormat("    BO   : %4d trades  WR %5.1f%%  PnL $%.2f", n_bo, 100.0 * w_bo / n_bo, pnl_bo);
   else Print("    BO   : 0 trades");
   if(n_vwap > 0)
      PrintFormat("    VWAP : %4d trades  WR %5.1f%%  PnL $%.2f", n_vwap, 100.0 * w_vwap / n_vwap, pnl_vwap);
   else Print("    VWAP : 0 trades");
   if(n_kz > 0)
      PrintFormat("    KZ   : %4d trades  WR %5.1f%%  PnL $%.2f", n_kz, 100.0 * w_kz / n_kz, pnl_kz);
   else Print("    KZ   : 0 trades");
}

//+------------------------------------------------------------------+
//| HELPERS                                                           |
//+------------------------------------------------------------------+
datetime ServerToUTC(datetime t) { return t - (datetime)(InpServerGMTOffsetHours * 3600); }

bool InHourRange(int h, int start_h, int end_h)
{
   if(start_h <= end_h) return h >= start_h && h < end_h;
   return h >= start_h || h < end_h;
}

bool IsNewBar()
{
   datetime t = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(t == g_last_bar) return false;
   g_last_bar = t;
   return true;
}

int CountMyPositions()
{
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(g_pos.SelectByIndex(i) && g_pos.Symbol() == _Symbol && g_pos.Magic() == InpMagic) n++;
   return n;
}

double NormalizeLot(double lot)
{
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lot = MathMax(minLot, MathMin(maxLot, lot));
   if(step > 0) lot = MathFloor(lot / step) * step;
   return NormalizeDouble(lot, 2);
}

double CalcLotByRisk(double sl_dist)
{
   if(InpFixedLot > 0) return NormalizeLot(InpFixedLot);
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk = eq * InpRiskPercent / 100.0;
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(ts <= 0 || tv <= 0 || sl_dist <= 0) return NormalizeLot(0.01);
   double loss_per_lot = (sl_dist / ts) * tv;
   if(loss_per_lot <= 0) return NormalizeLot(0.01);
   return NormalizeLot(risk / loss_per_lot);
}

//+------------------------------------------------------------------+
//| VWAP daily (anchored midnight UTC, tick volume)                   |
//+------------------------------------------------------------------+
void UpdateVWAP()
{
   // Update à partir de la bougie qui vient de clôturer (index 1)
   datetime bar_server = iTime(_Symbol, PERIOD_CURRENT, 1);
   datetime bar_utc    = ServerToUTC(bar_server);
   MqlDateTime dt; TimeToStruct(bar_utc, dt);
   datetime day = (datetime)(bar_utc - (dt.hour * 3600 + dt.min * 60 + dt.sec));

   if(day != g_vwap_day)
   {
      g_vwap_cum_tpv = 0;
      g_vwap_cum_vol = 0;
      g_vwap_day = day;
   }
   double h = iHigh (_Symbol, PERIOD_CURRENT, 1);
   double l = iLow  (_Symbol, PERIOD_CURRENT, 1);
   double c = iClose(_Symbol, PERIOD_CURRENT, 1);
   long   v = iTickVolume(_Symbol, PERIOD_CURRENT, 1);
   double tp = (h + l + c) / 3.0;
   g_vwap_cum_tpv += tp * (double)v;
   g_vwap_cum_vol += (double)v;
}

double GetVWAP() { return g_vwap_cum_vol > 0 ? g_vwap_cum_tpv / g_vwap_cum_vol : 0.0; }

//+------------------------------------------------------------------+
//| Indicator value getters (on bougie 1 = dernière close)            |
//+------------------------------------------------------------------+
double GetATR()
{
   double buf[]; ArraySetAsSeries(buf, true);
   if(CopyBuffer(g_atr_handle, 0, 0, 3, buf) <= 0) return 0;
   return buf[1];
}
double GetEMA9()
{
   double buf[]; ArraySetAsSeries(buf, true);
   if(CopyBuffer(g_ema9_handle, 0, 0, 3, buf) <= 0) return 0;
   return buf[1];
}
double GetHTF_EMA()
{
   double buf[]; ArraySetAsSeries(buf, true);
   if(CopyBuffer(g_htf_ema_handle, 0, 0, 3, buf) <= 0) return 0;
   return buf[0];
}

double GetVolMA()
{
   long vols[]; ArraySetAsSeries(vols, true);
   int got = CopyTickVolume(_Symbol, PERIOD_CURRENT, 0, InpVolMAPeriod + 2, vols);
   if(got <= 0) return 0;
   double sum = 0; int n = 0;
   for(int i = 1; i <= InpVolMAPeriod && i < got; i++) { sum += (double)vols[i]; n++; }
   return n > 0 ? sum / n : 0;
}

//+------------------------------------------------------------------+
//| Quality score (v2 formula)                                        |
//+------------------------------------------------------------------+
int CalcQuality(bool with_trend_ema, bool high_vol, double dist_vwap_pct, bool in_kz, bool htf_aligned)
{
   double s = 45.0;
   if(with_trend_ema) s += 15;
   if(htf_aligned)    s += 15;
   if(high_vol)       s += 10;
   if(dist_vwap_pct < 0.1)      s += 10;
   else if(dist_vwap_pct < 0.3) s += 5;
   if(in_kz)          s += 5;
   return (int)MathMin(s, 100.0);
}

//+------------------------------------------------------------------+
//| Asian Range : update state                                        |
//+------------------------------------------------------------------+
void UpdateAsianRange(int hour_utc, double atr)
{
   bool in_tyo = InHourRange(hour_utc, InpTokyoStart, InpTokyoEnd);
   double h_prev = iHigh(_Symbol, PERIOD_CURRENT, 1);
   double l_prev = iLow (_Symbol, PERIOD_CURRENT, 1);

   if(in_tyo)
   {
      if(!g_prev_in_tyo)
      {
         g_asian_high = h_prev;
         g_asian_low  = l_prev;
         g_asian_range_valid = false;
         g_asian_broken_up   = false;
         g_asian_broken_down = false;
         g_broken_bar_up_idx   = -1;
         g_broken_bar_down_idx = -1;
         g_long_taken  = false;
         g_short_taken = false;
         g_ranges_captured++;
         if(InpLogSessionEvents)
            PrintFormat("[SESSION] Tokyo START | h=%d utc", hour_utc);
      }
      else
      {
         g_asian_high = MathMax(g_asian_high, h_prev);
         g_asian_low  = MathMin(g_asian_low,  l_prev);
      }
   }

   if(g_prev_in_tyo && !in_tyo)
   {
      double r = g_asian_high - g_asian_low;
      double ratio = atr > 0 ? r / atr : 0;
      bool valid = (ratio >= InpRangeMinATRRatio && ratio <= InpRangeMaxATRRatio);
      g_asian_range_valid = valid;
      if(valid) g_ranges_validated++; else g_ranges_rejected_size++;
      if(InpLogSessionEvents)
         PrintFormat("[RANGE] Tokyo END | high=%s low=%s range/atr=%.2f => %s",
                     DoubleToString(g_asian_high, _Digits),
                     DoubleToString(g_asian_low,  _Digits),
                     ratio, valid ? "VALID" : "REJECTED");
   }

   g_prev_in_tyo = in_tyo;
}

//+------------------------------------------------------------------+
//| Track des breaks du range asiatique                               |
//+------------------------------------------------------------------+
void UpdateBreakTracking(int hour_utc)
{
   if(!g_asian_range_valid) return;
   bool in_ldn = InHourRange(hour_utc, InpLondonStart, InpLondonEnd);
   if(!in_ldn) return;

   double c1 = iClose(_Symbol, PERIOD_CURRENT, 1);
   double c2 = iClose(_Symbol, PERIOD_CURRENT, 2);

   if(!g_asian_broken_up && c2 <= g_asian_high && c1 > g_asian_high)
   {
      g_asian_broken_up = true;
      g_broken_bar_up_idx = Bars(_Symbol, PERIOD_CURRENT);
   }
   if(!g_asian_broken_down && c2 >= g_asian_low && c1 < g_asian_low)
   {
      g_asian_broken_down = true;
      g_broken_bar_down_idx = Bars(_Symbol, PERIOD_CURRENT);
   }
}

//+------------------------------------------------------------------+
//| KZ freshness update                                               |
//+------------------------------------------------------------------+
void UpdateKZState(int hour_utc, datetime bar_utc)
{
   bool in_l_kz = InHourRange(hour_utc, InpLondonKZStart, InpLondonKZEnd);
   bool in_n_kz = InHourRange(hour_utc, InpNYKZStart, InpNYKZEnd);

   if(in_l_kz && !g_prev_in_london_kz)
   {
      g_london_kz_start_utc = bar_utc;
      if(InpLogSessionEvents) PrintFormat("[KZ] London KZ START | h=%d utc", hour_utc);
   }
   if(in_n_kz && !g_prev_in_ny_kz)
   {
      g_ny_kz_start_utc = bar_utc;
      if(InpLogSessionEvents) PrintFormat("[KZ] NY KZ START | h=%d utc", hour_utc);
   }

   g_prev_in_london_kz = in_l_kz;
   g_prev_in_ny_kz     = in_n_kz;
}

bool IsInFreshKZ(int hour_utc, datetime bar_utc)
{
   bool in_l_kz = InHourRange(hour_utc, InpLondonKZStart, InpLondonKZEnd);
   bool in_n_kz = InHourRange(hour_utc, InpNYKZStart, InpNYKZEnd);
   if(in_l_kz && g_london_kz_start_utc > 0 && (bar_utc - g_london_kz_start_utc) <= InpKZFreshMinutes * 60) return true;
   if(in_n_kz && g_ny_kz_start_utc     > 0 && (bar_utc - g_ny_kz_start_utc)     <= InpKZFreshMinutes * 60) return true;
   return false;
}

//+------------------------------------------------------------------+
//| Signal struct                                                     |
//+------------------------------------------------------------------+
struct Signal
{
   bool   valid;
   string strategy;
   bool   is_long;
   double entry;
   double sl;
   double tp;
   double rr;
   int    quality;
};

Signal MakeEmpty() { Signal s; s.valid=false; s.strategy=""; s.is_long=false; s.entry=0; s.sl=0; s.tp=0; s.rr=0; s.quality=0; return s; }

//+------------------------------------------------------------------+
//| STRATÉGIE 1 : Asian Breakout                                      |
//+------------------------------------------------------------------+
Signal EvaluateAsianBO(int hour_utc, double atr, double ema9, double vwap, bool htf_up, bool htf_dn,
                       bool high_vol, bool in_london_kz)
{
   Signal s = MakeEmpty();
   if(!InpEnableAsianBO)   return s;
   if(!g_asian_range_valid) return s;
   if(!InHourRange(hour_utc, InpLondonStart, InpLondonEnd)) return s;

   double c1 = iClose(_Symbol, PERIOD_CURRENT, 1);
   double c2 = iClose(_Symbol, PERIOD_CURRENT, 2);
   double l1 = iLow  (_Symbol, PERIOD_CURRENT, 1);
   double h1 = iHigh (_Symbol, PERIOD_CURRENT, 1);
   double o1 = iOpen (_Symbol, PERIOD_CURRENT, 1);

   double range = g_asian_high - g_asian_low;
   int bar_now = Bars(_Symbol, PERIOD_CURRENT);

   // LONG
   if(g_long_taken) g_bo_skipped_taken++;
   else if(InpUseHTFTrend && !htf_up) g_bo_skipped_htf++;
   bool long_ok = !g_long_taken && (!InpUseHTFTrend || htf_up);
   if(long_ok)
   {
      bool trigger = false;
      if(InpRequireRetest)
      {
         if(!g_asian_broken_up) g_bo_skipped_no_break++;
         else if((bar_now - g_broken_bar_up_idx) > InpMaxRetestBars) g_bo_skipped_no_retest++;
         else if(l1 <= g_asian_high + atr * InpRetestToleranceATR && c1 > g_asian_high && c1 > o1)
            trigger = true;
         else g_bo_skipped_no_retest++;
      }
      else
      {
         if(c2 <= g_asian_high && c1 > g_asian_high) trigger = true;
      }

      if(trigger)
      {
         g_bo_potential_long++;
         s.valid    = true;
         s.strategy = "BO";
         s.is_long  = true;
         s.entry    = c1;
         s.sl       = g_asian_low;
         s.tp       = g_asian_high + range * InpDefaultRR;
         s.rr       = (s.tp - s.entry) / (s.entry - s.sl);
         bool with_ema = c1 > ema9;
         double dist_pct = vwap > 0 ? MathAbs(c1 - vwap) / c1 * 100.0 : 0;
         s.quality = CalcQuality(with_ema, high_vol, dist_pct, in_london_kz, htf_up);
         return s;
      }
   }

   // SHORT
   if(g_short_taken) g_bo_skipped_taken++;
   else if(InpUseHTFTrend && !htf_dn) g_bo_skipped_htf++;
   bool short_ok = !g_short_taken && (!InpUseHTFTrend || htf_dn);
   if(short_ok)
   {
      bool trigger = false;
      if(InpRequireRetest)
      {
         if(!g_asian_broken_down) g_bo_skipped_no_break++;
         else if((bar_now - g_broken_bar_down_idx) > InpMaxRetestBars) g_bo_skipped_no_retest++;
         else if(h1 >= g_asian_low - atr * InpRetestToleranceATR && c1 < g_asian_low && c1 < o1)
            trigger = true;
         else g_bo_skipped_no_retest++;
      }
      else
      {
         if(c2 >= g_asian_low && c1 < g_asian_low) trigger = true;
      }

      if(trigger)
      {
         g_bo_potential_short++;
         s.valid    = true;
         s.strategy = "BO";
         s.is_long  = false;
         s.entry    = c1;
         s.sl       = g_asian_high;
         s.tp       = g_asian_low - range * InpDefaultRR;
         s.rr       = (s.entry - s.tp) / (s.sl - s.entry);
         bool with_ema = c1 < ema9;
         double dist_pct = vwap > 0 ? MathAbs(c1 - vwap) / c1 * 100.0 : 0;
         s.quality = CalcQuality(with_ema, high_vol, dist_pct, in_london_kz, htf_dn);
         return s;
      }
   }

   return s;
}

//+------------------------------------------------------------------+
//| STRATÉGIE 2 : VWAP Bounce                                         |
//+------------------------------------------------------------------+
Signal EvaluateVWAP(double atr, double ema9, double vwap,
                    bool htf_up, bool htf_dn, bool high_vol, bool in_any_kz)
{
   Signal s = MakeEmpty();
   if(!InpEnableVWAP) return s;
   if(vwap <= 0)      return s;

   double c1 = iClose(_Symbol, PERIOD_CURRENT, 1);
   double c2 = iClose(_Symbol, PERIOD_CURRENT, 2);
   double dist = MathAbs(c1 - vwap);
   bool near_vwap = dist < atr * 0.3;

   // LONG : crossover au-dessus du VWAP
   if(c2 <= vwap && c1 > vwap)
   {
      g_vwap_crossovers_long++;
      if(!near_vwap)                       { g_vwap_skipped_far++;   return s; }
      if(InpUseHTFTrend && !htf_up)        { g_vwap_skipped_htf++;   return s; }
      bool with_ema = c1 > ema9;
      if(InpLocalTrendFilter && !with_ema) { g_vwap_skipped_trend++; return s; }
      if(InpVolumeFilter && !high_vol)     { g_vwap_skipped_vol++;   return s; }

      s.valid    = true;
      s.strategy = "VWAP";
      s.is_long  = true;
      s.entry    = c1;
      s.sl       = c1 - atr * InpATR_SL_VWAP;
      s.tp       = c1 + (c1 - s.sl) * InpDefaultRR;
      s.rr       = (s.tp - s.entry) / (s.entry - s.sl);
      double dist_pct = dist / c1 * 100.0;
      s.quality = CalcQuality(with_ema, high_vol, dist_pct, in_any_kz, htf_up);
      return s;
   }

   // SHORT : crossunder en-dessous du VWAP
   if(c2 >= vwap && c1 < vwap)
   {
      g_vwap_crossovers_short++;
      if(!near_vwap)                       { g_vwap_skipped_far++;   return s; }
      if(InpUseHTFTrend && !htf_dn)        { g_vwap_skipped_htf++;   return s; }
      bool with_ema = c1 < ema9;
      if(InpLocalTrendFilter && !with_ema) { g_vwap_skipped_trend++; return s; }
      if(InpVolumeFilter && !high_vol)     { g_vwap_skipped_vol++;   return s; }

      s.valid    = true;
      s.strategy = "VWAP";
      s.is_long  = false;
      s.entry    = c1;
      s.sl       = c1 + atr * InpATR_SL_VWAP;
      s.tp       = c1 - (s.sl - c1) * InpDefaultRR;
      s.rr       = (s.entry - s.tp) / (s.sl - s.entry);
      double dist_pct = dist / c1 * 100.0;
      s.quality = CalcQuality(with_ema, high_vol, dist_pct, in_any_kz, htf_dn);
      return s;
   }

   return s;
}

//+------------------------------------------------------------------+
//| STRATÉGIE 3 : Kill Zone Entries                                   |
//+------------------------------------------------------------------+
Signal EvaluateKZ(int hour_utc, datetime bar_utc, double atr, double ema9, double vwap,
                  bool htf_up, bool htf_dn, bool high_vol)
{
   Signal s = MakeEmpty();
   if(!InpEnableKZ) return s;

   bool in_l_kz = InHourRange(hour_utc, InpLondonKZStart, InpLondonKZEnd);
   bool in_n_kz = InHourRange(hour_utc, InpNYKZStart, InpNYKZEnd);
   bool in_any  = in_l_kz || in_n_kz;
   if(!in_any) return s;

   double c1 = iClose(_Symbol, PERIOD_CURRENT, 1);
   double c2 = iClose(_Symbol, PERIOD_CURRENT, 2);
   double ema_prev[]; ArraySetAsSeries(ema_prev, true);
   if(CopyBuffer(g_ema9_handle, 0, 0, 4, ema_prev) <= 0) return s;
   double ema1 = ema_prev[1];
   double ema2 = ema_prev[2];

   bool fresh = IsInFreshKZ(hour_utc, bar_utc);

   // LONG : close > vwap + crossover ema9
   if(c1 > vwap && c2 <= ema2 && c1 > ema1)
   {
      g_kz_crossovers_long++;
      if(InpKZFreshOnly && !fresh)     { g_kz_skipped_not_fresh++; return s; }
      if(InpUseHTFTrend && !htf_up)    { g_kz_skipped_htf++;       return s; }
      if(InpVolumeFilter && !high_vol) { g_kz_skipped_vol++;       return s; }

      s.valid    = true;
      s.strategy = in_l_kz ? "KZ-LDN" : "KZ-NY";
      s.is_long  = true;
      s.entry    = c1;
      s.sl       = c1 - atr * InpATR_SL_KZ;
      s.tp       = c1 + (c1 - s.sl) * InpDefaultRR;
      s.rr       = (s.tp - s.entry) / (s.entry - s.sl);
      double dist_pct = vwap > 0 ? MathAbs(c1 - vwap) / c1 * 100.0 : 0;
      s.quality = CalcQuality(true, high_vol, dist_pct, true, htf_up);
      return s;
   }

   // SHORT : close < vwap + crossunder ema9
   if(c1 < vwap && c2 >= ema2 && c1 < ema1)
   {
      g_kz_crossovers_short++;
      if(InpKZFreshOnly && !fresh)     { g_kz_skipped_not_fresh++; return s; }
      if(InpUseHTFTrend && !htf_dn)    { g_kz_skipped_htf++;       return s; }
      if(InpVolumeFilter && !high_vol) { g_kz_skipped_vol++;       return s; }

      s.valid    = true;
      s.strategy = in_l_kz ? "KZ-LDN" : "KZ-NY";
      s.is_long  = false;
      s.entry    = c1;
      s.sl       = c1 + atr * InpATR_SL_KZ;
      s.tp       = c1 - (s.sl - c1) * InpDefaultRR;
      s.rr       = (s.entry - s.tp) / (s.sl - s.entry);
      double dist_pct = vwap > 0 ? MathAbs(c1 - vwap) / c1 * 100.0 : 0;
      s.quality = CalcQuality(true, high_vol, dist_pct, true, htf_dn);
      return s;
   }

   return s;
}

//+------------------------------------------------------------------+
//| Logging vers le journal Expert ([TAG] style des autres EAs)       |
//+------------------------------------------------------------------+
void PrintSignalLog(const Signal &s, int hour_utc, double atr, double vwap,
                    double range_atr_ratio, bool in_fresh_kz, bool htf_up, bool htf_dn,
                    bool taken, string skip_reason, bool cooldown_active)
{
   if(!s.valid) return;
   if(!taken && !InpLogSkips) return;

   string dir = s.is_long ? "LONG" : "SHORT";
   string tag = taken ? "[SIGNAL]" : "[SKIP]";

   string base = StringFormat(
      "%s %s %s | entry=%s sl=%s tp=%s rr=%.2f q=%d",
      tag, s.strategy, dir,
      DoubleToString(s.entry, _Digits),
      DoubleToString(s.sl, _Digits),
      DoubleToString(s.tp, _Digits),
      s.rr, s.quality);

   if(!taken) base += " | reason=" + skip_reason;

   if(InpVerboseContext)
   {
      bool in_tyo = InHourRange(hour_utc, InpTokyoStart, InpTokyoEnd);
      bool in_ldn = InHourRange(hour_utc, InpLondonStart, InpLondonEnd);
      bool in_ny  = InHourRange(hour_utc, InpNYStart, InpNYEnd);
      bool in_lkz = InHourRange(hour_utc, InpLondonKZStart, InpLondonKZEnd);
      bool in_nkz = InHourRange(hour_utc, InpNYKZStart, InpNYKZEnd);
      base += StringFormat(
         " | tyo=%d ldn=%d ny=%d lkz=%d nkz=%d fresh=%d htf=%s r/atr=%.2f atr=%s vwap=%s cd=%d",
         in_tyo ? 1 : 0, in_ldn ? 1 : 0, in_ny ? 1 : 0,
         in_lkz ? 1 : 0, in_nkz ? 1 : 0,
         in_fresh_kz ? 1 : 0,
         htf_up ? "UP" : (htf_dn ? "DN" : "--"),
         range_atr_ratio,
         DoubleToString(atr, _Digits),
         DoubleToString(vwap, _Digits),
         cooldown_active ? 1 : 0);
   }

   Print(base);
}

//+------------------------------------------------------------------+
//| Execute the selected signal                                       |
//+------------------------------------------------------------------+
bool Execute(const Signal &s)
{
   if(!s.valid) return false;
   if(CountMyPositions() >= InpMaxPositions) return false;
   int spread = (int)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > InpMaxSpreadPoints) return false;

   double sl_dist = MathAbs(s.entry - s.sl);
   double lot = CalcLotByRisk(sl_dist);
   string comment = s.strategy + " Q" + IntegerToString(s.quality);

   bool ok;
   if(s.is_long) ok = g_trade.Buy (lot, _Symbol, 0, s.sl, s.tp, comment);
   else          ok = g_trade.Sell(lot, _Symbol, 0, s.sl, s.tp, comment);

   if(!ok)
   {
      PrintFormat("[OPEN FAIL] %s %s code=%d desc=%s",
                  s.strategy, s.is_long ? "LONG" : "SHORT",
                  g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
      return false;
   }

   PrintFormat("[OPEN OK] %s %s lot=%.2f entry=%s sl=%s tp=%s q=%d",
               s.strategy, s.is_long ? "LONG" : "SHORT", lot,
               DoubleToString(s.entry, _Digits),
               DoubleToString(s.sl, _Digits),
               DoubleToString(s.tp, _Digits),
               s.quality);

   // Update state
   g_signals_taken++;
   if(StringFind(s.strategy, "BO") >= 0)   g_signals_bo++;
   if(s.strategy == "VWAP")                g_signals_vwap++;
   if(StringFind(s.strategy, "KZ") >= 0)   g_signals_kz++;

   if(s.strategy == "BO")
   {
      if(s.is_long) g_long_taken = true; else g_short_taken = true;
   }

   g_last_signal_bar_idx = Bars(_Symbol, PERIOD_CURRENT);
   return true;
}

//+------------------------------------------------------------------+
//| OnTick                                                            |
//+------------------------------------------------------------------+
void OnTick()
{
   if(!IsNewBar()) return;

   if(Bars(_Symbol, PERIOD_CURRENT) < 200)
   {
      if(g_bars_processed == 0) Print("[INIT] warming up (need >=200 bars, waiting...)");
      return;
   }

   g_bars_processed++;
   if(g_bars_processed == 1)
      Print("[INIT] first bar processed — EA is running, indicators OK");

   // Heartbeat périodique
   if(InpHeartbeatBars > 0 && g_bars_processed % InpHeartbeatBars == 0)
      PrintFormat("[HB] bars_processed=%d signals_taken=%d skipped(q/cd/htf)=%d/%d/%d",
                  g_bars_processed, g_signals_taken,
                  g_signals_skipped_quality, g_signals_skipped_cooldown, g_signals_skipped_htf);

   // Indicateurs
   double atr  = GetATR();
   double ema9 = GetEMA9();
   double htf_ema = GetHTF_EMA();
   if(atr <= 0 || ema9 <= 0 || htf_ema <= 0)
   {
      if(InpLogSkips)
         PrintFormat("[SKIP] indicators not ready (atr=%g ema9=%g htf=%g)", atr, ema9, htf_ema);
      return;
   }

   UpdateVWAP();
   double vwap = GetVWAP();

   // Heure UTC et sessions/KZ
   datetime bar_server = iTime(_Symbol, PERIOD_CURRENT, 1);   // bougie qui vient de fermer
   datetime bar_utc    = ServerToUTC(bar_server);
   MqlDateTime dt; TimeToStruct(bar_utc, dt);
   int hour_utc = dt.hour;

   UpdateAsianRange(hour_utc, atr);
   UpdateBreakTracking(hour_utc);
   UpdateKZState(hour_utc, bar_utc);

   // Filtres contexte
   double c1 = iClose(_Symbol, PERIOD_CURRENT, 1);
   bool htf_up = c1 > htf_ema;
   bool htf_dn = c1 < htf_ema;

   double vol_ma = GetVolMA();
   long   v1 = iTickVolume(_Symbol, PERIOD_CURRENT, 1);
   bool   high_vol = vol_ma > 0 && (double)v1 > vol_ma;

   bool in_london_kz = InHourRange(hour_utc, InpLondonKZStart, InpLondonKZEnd);
   bool in_ny_kz     = InHourRange(hour_utc, InpNYKZStart, InpNYKZEnd);
   bool in_any_kz    = in_london_kz || in_ny_kz;
   bool in_fresh_kz  = IsInFreshKZ(hour_utc, bar_utc);

   // Counters diagnostiques
   if(InHourRange(hour_utc, InpTokyoStart, InpTokyoEnd))   g_bars_tyo++;
   if(InHourRange(hour_utc, InpLondonStart, InpLondonEnd)) g_bars_ldn++;
   if(InHourRange(hour_utc, InpNYStart, InpNYEnd))         g_bars_ny++;
   if(in_london_kz) g_bars_lkz++;
   if(in_ny_kz)     g_bars_nkz++;
   if(in_fresh_kz)  g_bars_fresh_kz++;

   double range_atr_ratio = (atr > 0 && g_asian_high > 0 && g_asian_low > 0)
                            ? (g_asian_high - g_asian_low) / atr : 0.0;

   // Évaluation des 3 stratégies
   Signal s_bo   = EvaluateAsianBO(hour_utc, atr, ema9, vwap, htf_up, htf_dn, high_vol, in_london_kz);
   Signal s_vwap = EvaluateVWAP(atr, ema9, vwap, htf_up, htf_dn, high_vol, in_any_kz);
   Signal s_kz   = EvaluateKZ(hour_utc, bar_utc, atr, ema9, vwap, htf_up, htf_dn, high_vol);

   // Priorité KZ > BO > VWAP
   Signal selected = MakeEmpty();
   if(InpPriorityMode)
   {
      if(s_kz.valid)       selected = s_kz;
      else if(s_bo.valid)  selected = s_bo;
      else if(s_vwap.valid)selected = s_vwap;
   }
   else
   {
      if(s_kz.valid)            selected = s_kz;
      else if(s_bo.valid)       selected = s_bo;
      else if(s_vwap.valid)     selected = s_vwap;
      // (même ordre en non-priorité pour simplifier : si besoin,
      //  on peut logger individuellement les 3 et choisir la meilleure qualité)
   }

   // Cooldown
   int bar_now = Bars(_Symbol, PERIOD_CURRENT);
   bool cooldown = (bar_now - g_last_signal_bar_idx) < InpCooldownBars;

   // Décision + logging
   if(!selected.valid)
   {
      if(InpLogSkips && (s_bo.valid || s_vwap.valid || s_kz.valid))
      {
         // jamais censé arriver avec la sélection ci-dessus, mais safe
      }
      return;
   }

   string skip_reason = "";
   bool will_take = true;

   if(selected.quality < InpMinQuality)
   {
      will_take = false;
      skip_reason = "quality";
      g_signals_skipped_quality++;
   }
   else if(cooldown)
   {
      will_take = false;
      skip_reason = "cooldown";
      g_signals_skipped_cooldown++;
   }
   else if(InpUseHTFTrend && ((selected.is_long && !htf_up) || (!selected.is_long && !htf_dn)))
   {
      will_take = false;
      skip_reason = "htf";
      g_signals_skipped_htf++;
   }

   bool taken = false;
   if(will_take) taken = Execute(selected);

   PrintSignalLog(selected, hour_utc, atr, vwap, range_atr_ratio,
                  in_fresh_kz, htf_up, htf_dn, taken,
                  taken ? "" : (skip_reason == "" ? "exec_failed" : skip_reason),
                  cooldown);
}

//+------------------------------------------------------------------+
