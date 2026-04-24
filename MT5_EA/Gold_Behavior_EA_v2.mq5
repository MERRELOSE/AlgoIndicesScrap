//+------------------------------------------------------------------+
//|                                     Gold_Behavior_EA_v2.mq5       |
//|                       XAUUSD H1 behavioral-recipe trader          |
//|                       AlgoIndicesScrap Project                    |
//+------------------------------------------------------------------+
//  Validated OUT-OF-SAMPLE on XAUUSD H1 (5 years, Deriv MT5 data):
//
//  Base rate (big LONG 2R move): 34.3%
//
//  v1 LONG recipes (shorts disabled - too weak even at R:R 2:1):
//    GL1: atr_14_q3 + bb_width_q3 + h_5 (20-23h UTC)         -> OOS WR 51.9%
//    GL2: bb_width_q3 + dist_ema200_q4 + dist_ema50_q2       -> OOS WR 51.9%
//    GL3: dist_ema200_q4 + dist_ema50_q2 + not_in_london_0   -> OOS WR 49.3%
//    GL4: bb_pos_q2 + bb_width_q3 + rsi_14_q3                -> OOS WR 47.1%
//
//  v2 ADDITIONS (strict triple-split hunter, VAL+TEST double-validated):
//    GL5: bb_pos_q2 + bb_width_q3 + htf_trend_1 + rsi_14_q3     -> Val 46.8% / Test 47.1%
//    GL6: bb_pos_q2 + bb_width_q3 + rsi_14_q3 + trend_50_200_1  -> Val 45.6% / Test 47.1%
//    (GL4 refinements with extra trend filter: H4 bullish / EMA50>EMA200)
//+------------------------------------------------------------------+
#property copyright "AlgoIndicesScrap"
#property version   "2.00"
#property description "XAUUSD H1 behavioral EA v2 - 6 LONG recipes validated OOS, R:R 2:1."
#property description "v2: added GL5 (htf_trend_1) + GL6 (trend_50_200_1) from strict hunter."
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//+------------------------------------------------------------------+
//| INPUTS                                                            |
//+------------------------------------------------------------------+
input group "=== Risk ==="
input double InpRiskPercent      = 1.0;    // Risk per trade (% equity)
input double InpFixedLot         = 0.0;    // Fixed lot (0 = risk-based)
input double InpTPatATR          = 2.0;    // TP in ATR (R:R target)
input double InpSLatATR          = 1.0;    // SL in ATR
input int    InpMaxSpreadPoints  = 50;     // Skip entry if spread exceeds
input int    InpMagic            = 780002;  // v2: different magic from v1

input group "=== Recipes enable ==="
input bool   InpEnableGL1 = true;   // atr_q3 + bb_width_q3 + h_5
input bool   InpEnableGL2 = true;   // bb_width_q3 + dist_ema200_q4 + dist_ema50_q2
input bool   InpEnableGL3 = true;   // dist_ema200_q4 + dist_ema50_q2 + NOT London
input bool   InpEnableGL4 = true;   // bb_pos_q2 + bb_width_q3 + rsi_14_q3
input bool   InpEnableGL5 = true;   // v2: bb_pos_q2 + bb_width_q3 + htf_trend_1 + rsi_14_q3
input bool   InpEnableGL6 = true;   // v2: bb_pos_q2 + bb_width_q3 + rsi_14_q3 + trend_50_200_1
input bool   InpGL3RequireConfluence = true; // GL3 lost money solo (-$10/18 tr). Force it to fire only with another recipe.

input group "=== Hour filter (UTC) - disable losing hours ==="
input string InpForbiddenHoursCSV = "3,4,6,7,10,11,18"; // Hours of day where trading is skipped (comma separated)

input group "=== Safety ==="
input int    InpMaxLossStreak    = 0;    // Stop trading after N consecutive SLs (0 = disabled)
input int    InpLossStreakCooldownBars = 24; // Bars to wait after loss-streak circuit breaker

input group "=== Regime filter (skip choppy markets) ==="
// Both filters OFF by default — v1.20 was better without them.
// Keep available for experimentation.
input bool   InpUseEMA200Slope   = false;  // Only trade when EMA200 is rising
input int    InpEMA200SlopeBars  = 50;
input bool   InpUseADXFilter     = false;
input int    InpADXPeriod        = 14;
input double InpADXMin           = 20.0;

input group "=== Indicator periods ==="
input int    InpATRPeriod        = 14;
input int    InpBBPeriod         = 20;
input double InpBBStd            = 2.0;
input int    InpEMA50Period      = 50;
input int    InpEMA200Period     = 200;
input int    InpRSIPeriod        = 14;
input int    InpPercentileWindow = 500;    // Rolling window for quartile bins

input group "=== Trade mgmt ==="
input int    InpCooldownBars     = 3;
input int    InpMaxPositions     = 1;
input bool   InpEnableTrailing   = false;
input double InpTrailStartR      = 1.0;
input double InpTrailATR         = 1.0;

input group "=== Logging ==="
input bool   InpLogSignals       = true;   // Print each entry/exit to Journal (live + backtest)
input bool   InpLogSkips         = false;  // Print every skip reason (noisy)
input bool   InpLogEveryBar      = false;  // Print condition snapshot each bar (very noisy)
input bool   InpPrintSummary     = true;   // Print full summary report at end of backtest

//+------------------------------------------------------------------+
//| GLOBALS                                                           |
//+------------------------------------------------------------------+
CTrade         g_trade;
CPositionInfo  g_pos;
int            g_atr_handle = INVALID_HANDLE;
int            g_bb_handle = INVALID_HANDLE;
int            g_ema50_handle = INVALID_HANDLE;
int            g_ema200_handle = INVALID_HANDLE;
int            g_rsi_handle = INVALID_HANDLE;
int            g_adx_handle = INVALID_HANDLE;
// v2: H4 handles for htf_trend (GL5)
int            g_h4_ema21_handle = INVALID_HANDLE;
int            g_h4_ema50_handle = INVALID_HANDLE;
datetime       g_last_bar = 0;
int            g_last_trade_bar_idx = -9999;

// Hour filter: array of 24 booleans parsed from InpForbiddenHoursCSV
bool           g_hour_blocked[24];
// Loss-streak breaker state
int            g_current_loss_streak = 0;
int            g_loss_streak_resume_bar = -1;
ulong          g_last_seen_deal_ticket = 0;  // last history deal we accounted

//+------------------------------------------------------------------+
void ParseForbiddenHours()
{
   for(int i = 0; i < 24; i++) g_hour_blocked[i] = false;
   string s = InpForbiddenHoursCSV;
   StringTrimLeft(s); StringTrimRight(s);
   if(StringLen(s) == 0) return;
   string parts[];
   int n = StringSplit(s, ',', parts);
   for(int i = 0; i < n; i++)
   {
      StringTrimLeft(parts[i]); StringTrimRight(parts[i]);
      int h = (int)StringToInteger(parts[i]);
      if(h >= 0 && h < 24) g_hour_blocked[h] = true;
   }
}

int OnInit()
{
   if(_Period != PERIOD_H1)
      Print("WARNING: Gold_Behavior_EA is designed for H1. Current TF: ", EnumToString(_Period));

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_trade.SetMarginMode();
   g_trade.SetDeviationInPoints(20);

   ParseForbiddenHours();
   g_current_loss_streak = 0;
   g_loss_streak_resume_bar = -1;
   g_last_seen_deal_ticket = 0;

   g_atr_handle    = iATR(_Symbol, PERIOD_CURRENT, InpATRPeriod);
   g_bb_handle     = iBands(_Symbol, PERIOD_CURRENT, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE);
   g_ema50_handle  = iMA(_Symbol, PERIOD_CURRENT, InpEMA50Period, 0, MODE_EMA, PRICE_CLOSE);
   g_ema200_handle = iMA(_Symbol, PERIOD_CURRENT, InpEMA200Period, 0, MODE_EMA, PRICE_CLOSE);
   g_rsi_handle    = iRSI(_Symbol, PERIOD_CURRENT, InpRSIPeriod, PRICE_CLOSE);
   g_adx_handle    = iADX(_Symbol, PERIOD_CURRENT, InpADXPeriod);
   // v2: H4 EMAs for htf_trend_1 (GL5)
   g_h4_ema21_handle = iMA(_Symbol, PERIOD_H4, 21, 0, MODE_EMA, PRICE_CLOSE);
   g_h4_ema50_handle = iMA(_Symbol, PERIOD_H4, 50, 0, MODE_EMA, PRICE_CLOSE);

   if(g_atr_handle == INVALID_HANDLE || g_bb_handle == INVALID_HANDLE ||
      g_ema50_handle == INVALID_HANDLE || g_ema200_handle == INVALID_HANDLE ||
      g_rsi_handle == INVALID_HANDLE || g_adx_handle == INVALID_HANDLE ||
      g_h4_ema21_handle == INVALID_HANDLE || g_h4_ema50_handle == INVALID_HANDLE)
   {
      Print("ERROR: Failed to init indicator handles");
      return INIT_FAILED;
   }
   PrintFormat("=== Gold Behavior EA v2.00 init ===");
   PrintFormat("  Symbol=%s TF=%s Magic=%d", _Symbol, EnumToString(_Period), InpMagic);
   PrintFormat("  Risk=%.2f%% | R:R %.1f:%.1f | Max spread=%d pts",
               InpRiskPercent, InpTPatATR, InpSLatATR, InpMaxSpreadPoints);
   PrintFormat("  Recipes enabled: GL1=%s GL2=%s GL3=%s GL4=%s GL5=%s GL6=%s  (GL3 confluence-req=%s)",
               InpEnableGL1 ? "Y" : "N", InpEnableGL2 ? "Y" : "N",
               InpEnableGL3 ? "Y" : "N", InpEnableGL4 ? "Y" : "N",
               InpEnableGL5 ? "Y" : "N", InpEnableGL6 ? "Y" : "N",
               InpGL3RequireConfluence ? "Y" : "N");
   string blocked_list = "";
   for(int h = 0; h < 24; h++) if(g_hour_blocked[h]) blocked_list += IntegerToString(h) + " ";
   PrintFormat("  Forbidden hours UTC: %s", blocked_list == "" ? "(none)" : blocked_list);
   if(InpMaxLossStreak > 0)
      PrintFormat("  Loss-streak breaker: stop after %d SLs, cooldown %d bars",
                  InpMaxLossStreak, InpLossStreakCooldownBars);
   PrintFormat("  Regime filter: EMA200 slope=%s (lookback %d), ADX=%s (>= %.1f)",
               InpUseEMA200Slope ? "ON" : "OFF", InpEMA200SlopeBars,
               InpUseADXFilter ? "ON" : "OFF", InpADXMin);
   PrintFormat("  Percentile window: %d bars (~%.1f weeks H1)",
               InpPercentileWindow, InpPercentileWindow/168.0);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(g_atr_handle != INVALID_HANDLE) IndicatorRelease(g_atr_handle);
   if(g_bb_handle != INVALID_HANDLE) IndicatorRelease(g_bb_handle);
   if(g_ema50_handle != INVALID_HANDLE) IndicatorRelease(g_ema50_handle);
   if(g_ema200_handle != INVALID_HANDLE) IndicatorRelease(g_ema200_handle);
   if(g_rsi_handle != INVALID_HANDLE) IndicatorRelease(g_rsi_handle);
   if(g_adx_handle != INVALID_HANDLE) IndicatorRelease(g_adx_handle);
   if(g_h4_ema21_handle != INVALID_HANDLE) IndicatorRelease(g_h4_ema21_handle);
   if(g_h4_ema50_handle != INVALID_HANDLE) IndicatorRelease(g_h4_ema50_handle);

   // Only print the big summary when running in Strategy Tester
   if(InpPrintSummary && MQLInfoInteger(MQL_TESTER))
      PrintSummaryReport();
}

//+------------------------------------------------------------------+
//| Helpers                                                           |
//+------------------------------------------------------------------+
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
   {
      if(g_pos.SelectByIndex(i) && g_pos.Symbol() == _Symbol && g_pos.Magic() == InpMagic) n++;
   }
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

double CalcLotByRisk(double sl_price_dist)
{
   if(InpFixedLot > 0) return NormalizeLot(InpFixedLot);
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk = eq * InpRiskPercent / 100.0;
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(ts <= 0 || tv <= 0 || sl_price_dist <= 0) return NormalizeLot(0.01);
   double loss_per_lot = (sl_price_dist / ts) * tv;
   if(loss_per_lot <= 0) return NormalizeLot(0.01);
   return NormalizeLot(risk / loss_per_lot);
}

//+------------------------------------------------------------------+
//| Regime filter: is the market in a tradeable trending state?       |
//| Returns (true, reason_desc) where desc = ""  if OK or error msg  |
//+------------------------------------------------------------------+
bool CheckRegime(string &why)
{
   why = "";

   // EMA200 slope check: current EMA200 > EMA200 N bars ago
   if(InpUseEMA200Slope)
   {
      int need = InpEMA200SlopeBars + 2;
      double e[];
      ArraySetAsSeries(e, true);
      if(CopyBuffer(g_ema200_handle, 0, 0, need, e) <= 0)
      { why = "ema200 copy fail"; return false; }
      if(e[1] <= e[InpEMA200SlopeBars])
      {
         why = StringFormat("EMA200 flat/down (now=%.2f vs %db ago=%.2f)",
                            e[1], InpEMA200SlopeBars, e[InpEMA200SlopeBars]);
         return false;
      }
   }

   // ADX check: ADX must be above threshold
   if(InpUseADXFilter)
   {
      double a[];
      ArraySetAsSeries(a, true);
      if(CopyBuffer(g_adx_handle, 0, 0, 2, a) <= 0)
      { why = "adx copy fail"; return false; }
      if(a[1] < InpADXMin)
      {
         why = StringFormat("ADX %.1f < min %.1f (no trend)", a[1], InpADXMin);
         return false;
      }
   }

   return true;
}

double PctileRank(const double &series[], int N, double value)
{
   if(N < 10) return 0.5;
   int count = 0, valid = 0;
   for(int i = 0; i < N; i++)
   {
      double v = series[i];
      if(v == EMPTY_VALUE) continue;
      valid++;
      if(v <= value) count++;
   }
   if(valid == 0) return 0.5;
   return (double)count / valid;
}

//+------------------------------------------------------------------+
//| Evaluate all conditions for the last closed bar                   |
//+------------------------------------------------------------------+
struct Conditions {
   bool   ok;
   double pr_atr, pr_bb_pos, pr_bb_width, pr_dist_ema50, pr_dist_ema200, pr_rsi;
   bool   atr_q3, bb_width_q3, bb_pos_q2, dist_ema200_q4, dist_ema50_q2, rsi_14_q3;
   int    hour_utc;
   bool   h_5;
   bool   sess_london_on;
   // v2 additions for GL5/GL6
   bool   htf_trend_1;       // H4 EMA21 > EMA50 (bullish)
   bool   trend_50_200_1;    // H1 EMA50 > EMA200 (bullish)
};

Conditions EvaluateConditions()
{
   Conditions c;
   c.ok = false;

   int need = InpPercentileWindow + 50;
   double H[], L[], C[], A[], BU[], BD[], BM[], E50[], E200[], R[];
   ArraySetAsSeries(H, true); ArraySetAsSeries(L, true); ArraySetAsSeries(C, true);
   ArraySetAsSeries(A, true); ArraySetAsSeries(BU, true); ArraySetAsSeries(BD, true);
   ArraySetAsSeries(BM, true); ArraySetAsSeries(E50, true); ArraySetAsSeries(E200, true);
   ArraySetAsSeries(R, true);

   if(CopyHigh (_Symbol, PERIOD_CURRENT, 0, need, H) <= 0) return c;
   if(CopyLow  (_Symbol, PERIOD_CURRENT, 0, need, L) <= 0) return c;
   if(CopyClose(_Symbol, PERIOD_CURRENT, 0, need, C) <= 0) return c;
   if(CopyBuffer(g_atr_handle,    0, 0, need, A)    <= 0) return c;
   if(CopyBuffer(g_bb_handle,     1, 0, need, BU)   <= 0) return c;
   if(CopyBuffer(g_bb_handle,     2, 0, need, BD)   <= 0) return c;
   if(CopyBuffer(g_bb_handle,     0, 0, need, BM)   <= 0) return c;
   if(CopyBuffer(g_ema50_handle,  0, 0, need, E50)  <= 0) return c;
   if(CopyBuffer(g_ema200_handle, 0, 0, need, E200) <= 0) return c;
   if(CopyBuffer(g_rsi_handle,    0, 0, need, R)    <= 0) return c;

   int i = 1;
   if(A[i] <= 0 || BM[i] <= 0 || C[i] <= 0 || E50[i] <= 0 || E200[i] <= 0) return c;

   double atr_i         = A[i];
   double bb_pos_i      = (BU[i] - BD[i] > 0) ? (C[i] - BD[i]) / (BU[i] - BD[i]) : 0.5;
   double bb_width_i    = (BU[i] - BD[i]) / BM[i];
   double dist_ema50_i  = (C[i] - E50[i]) / C[i];
   double dist_ema200_i = (C[i] - E200[i]) / C[i];
   double rsi_i         = R[i];

   double s_atr[], s_bbp[], s_bbw[], s_de50[], s_de200[], s_rsi[];
   ArrayResize(s_atr,    InpPercentileWindow);
   ArrayResize(s_bbp,    InpPercentileWindow);
   ArrayResize(s_bbw,    InpPercentileWindow);
   ArrayResize(s_de50,   InpPercentileWindow);
   ArrayResize(s_de200,  InpPercentileWindow);
   ArrayResize(s_rsi,    InpPercentileWindow);

   for(int k = 0; k < InpPercentileWindow; k++)
   {
      int j = i + k;
      s_atr[k]    = A[j];
      s_bbp[k]    = (BU[j] - BD[j] > 0) ? (C[j] - BD[j]) / (BU[j] - BD[j]) : 0.5;
      s_bbw[k]    = (BM[j] > 0) ? (BU[j] - BD[j]) / BM[j] : 0.0;
      s_de50[k]   = (C[j] > 0) ? (C[j] - E50[j]) / C[j] : 0.0;
      s_de200[k]  = (C[j] > 0) ? (C[j] - E200[j]) / C[j] : 0.0;
      s_rsi[k]    = R[j];
   }

   c.pr_atr         = PctileRank(s_atr,   InpPercentileWindow, atr_i);
   c.pr_bb_pos      = PctileRank(s_bbp,   InpPercentileWindow, bb_pos_i);
   c.pr_bb_width    = PctileRank(s_bbw,   InpPercentileWindow, bb_width_i);
   c.pr_dist_ema50  = PctileRank(s_de50,  InpPercentileWindow, dist_ema50_i);
   c.pr_dist_ema200 = PctileRank(s_de200, InpPercentileWindow, dist_ema200_i);
   c.pr_rsi         = PctileRank(s_rsi,   InpPercentileWindow, rsi_i);

   c.atr_q3         = (c.pr_atr         > 0.50 && c.pr_atr         <= 0.75);
   c.bb_width_q3    = (c.pr_bb_width    > 0.50 && c.pr_bb_width    <= 0.75);
   c.bb_pos_q2      = (c.pr_bb_pos      > 0.25 && c.pr_bb_pos      <= 0.50);
   c.dist_ema200_q4 = (c.pr_dist_ema200 > 0.75);
   c.dist_ema50_q2  = (c.pr_dist_ema50  > 0.25 && c.pr_dist_ema50  <= 0.50);
   c.rsi_14_q3      = (c.pr_rsi         > 0.50 && c.pr_rsi         <= 0.75);

   MqlDateTime mdt;
   TimeToStruct(iTime(_Symbol, PERIOD_CURRENT, i), mdt);
   c.hour_utc        = mdt.hour;
   c.h_5             = ((mdt.hour / 4) == 5);
   c.sess_london_on  = (mdt.hour >= 7 && mdt.hour < 16);

   // v2: H1 trend_50_200 (EMA50 > EMA200 on last closed bar)
   c.trend_50_200_1 = (E50[i] > E200[i]);

   // v2: H4 htf_trend_1 (H4 EMA21 > EMA50 at last closed H4 bar)
   c.htf_trend_1 = false;
   double h21[], h50[];
   ArraySetAsSeries(h21, true); ArraySetAsSeries(h50, true);
   // shift 1 to use last closed H4 bar (no look-ahead)
   if(CopyBuffer(g_h4_ema21_handle, 0, 1, 1, h21) == 1 &&
      CopyBuffer(g_h4_ema50_handle, 0, 1, 1, h50) == 1)
   {
      c.htf_trend_1 = (h21[0] > h50[0]);
   }

   c.ok = true;
   return c;
}

struct MatchResult {
   int    direction;
   string matched;
};

MatchResult MatchRecipes(const Conditions &c)
{
   MatchResult r;
   r.direction = 0;
   r.matched = "";
   if(!c.ok) return r;

   bool GL1 = InpEnableGL1 && c.atr_q3 && c.bb_width_q3 && c.h_5;
   bool GL2 = InpEnableGL2 && c.bb_width_q3 && c.dist_ema200_q4 && c.dist_ema50_q2;
   bool GL3 = InpEnableGL3 && c.dist_ema200_q4 && c.dist_ema50_q2 && !c.sess_london_on;
   bool GL4 = InpEnableGL4 && c.bb_pos_q2 && c.bb_width_q3 && c.rsi_14_q3;
   // v2: GL5 = GL4 + htf_trend_1 (H4 bullish). GL6 = GL4 + trend_50_200_1 (H1 EMA50>EMA200)
   bool GL5 = InpEnableGL5 && c.bb_pos_q2 && c.bb_width_q3 && c.rsi_14_q3 && c.htf_trend_1;
   bool GL6 = InpEnableGL6 && c.bb_pos_q2 && c.bb_width_q3 && c.rsi_14_q3 && c.trend_50_200_1;

   // GL3 solo lost money in backtest (-$10/18 trades, WR 33%).
   // Force it to fire only when at least one other recipe also triggers.
   if(InpGL3RequireConfluence && GL3 && !(GL1 || GL2 || GL4 || GL5 || GL6)) GL3 = false;

   if(GL1 || GL2 || GL3 || GL4 || GL5 || GL6)
   {
      r.direction = +1;
      if(GL1) r.matched += "GL1 ";
      if(GL2) r.matched += "GL2 ";
      if(GL3) r.matched += "GL3 ";
      if(GL4) r.matched += "GL4 ";
      if(GL5) r.matched += "GL5 ";
      if(GL6) r.matched += "GL6 ";
   }
   return r;
}

void LogContext(const Conditions &c, string prefix)
{
   if(!InpLogSignals) return;
   PrintFormat("%s pr[atr=%.2f bbp=%.2f bbw=%.2f de50=%.2f de200=%.2f rsi=%.2f] "
               "flags[atrQ3=%d bbwQ3=%d bbpQ2=%d de200Q4=%d de50Q2=%d rsiQ3=%d h5=%d lon=%d htfB=%d tr50200=%d]",
               prefix, c.pr_atr, c.pr_bb_pos, c.pr_bb_width,
               c.pr_dist_ema50, c.pr_dist_ema200, c.pr_rsi,
               (int)c.atr_q3, (int)c.bb_width_q3, (int)c.bb_pos_q2,
               (int)c.dist_ema200_q4, (int)c.dist_ema50_q2, (int)c.rsi_14_q3,
               (int)c.h_5, (int)c.sess_london_on,
               (int)c.htf_trend_1, (int)c.trend_50_200_1);
}

void TryOpen()
{
   int total_bars = Bars(_Symbol, PERIOD_CURRENT);
   if(total_bars - g_last_trade_bar_idx < InpCooldownBars)
   {
      if(InpLogSkips) PrintFormat("[SKIP] cooldown");
      return;
   }

   // Loss-streak circuit breaker
   if(InpMaxLossStreak > 0 && g_loss_streak_resume_bar > 0 &&
      total_bars < g_loss_streak_resume_bar)
   {
      if(InpLogSkips)
         PrintFormat("[SKIP] loss-streak breaker active (resume at bar %d)", g_loss_streak_resume_bar);
      return;
   }

   // Forbidden hour filter
   MqlDateTime now_dt;
   TimeToStruct(iTime(_Symbol, PERIOD_CURRENT, 0), now_dt);
   int hour_now = now_dt.hour;
   if(hour_now >= 0 && hour_now < 24 && g_hour_blocked[hour_now])
   {
      if(InpLogSkips) PrintFormat("[SKIP] hour %d is forbidden", hour_now);
      return;
   }

   // Regime filter (choppy market → skip)
   string regime_why;
   if(!CheckRegime(regime_why))
   {
      if(InpLogSkips) PrintFormat("[SKIP] regime: %s", regime_why);
      return;
   }

   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > InpMaxSpreadPoints)
   {
      if(InpLogSkips) PrintFormat("[SKIP] spread=%d > max=%d", (int)spread, InpMaxSpreadPoints);
      return;
   }

   if(CountMyPositions() >= InpMaxPositions) return;

   Conditions c = EvaluateConditions();
   if(!c.ok) return;
   if(InpLogEveryBar) LogContext(c, "[CTX]");

   MatchResult m = MatchRecipes(c);
   if(m.direction == 0) return;

   double atr_buf[1];
   if(CopyBuffer(g_atr_handle, 0, 1, 1, atr_buf) <= 0) return;
   double atr_i = atr_buf[0];
   if(atr_i <= 0) return;

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   double entry, sl, tp;
   if(m.direction == +1)
   {
      entry = ask;
      sl    = entry - InpSLatATR * atr_i;
      tp    = entry + InpTPatATR * atr_i;
   }
   else
   {
      entry = bid;
      sl    = entry + InpSLatATR * atr_i;
      tp    = entry - InpTPatATR * atr_i;
   }

   double sl_dist = MathAbs(entry - sl);
   double lot = CalcLotByRisk(sl_dist);
   if(lot <= 0) return;

   string comment = StringFormat("Gold %s", m.matched);

   if(InpLogSignals)
      PrintFormat("[SIGNAL] %s | spread=%d | %s",
                  m.direction == +1 ? "BUY" : "SELL", (int)spread, m.matched);

   bool ok = (m.direction == +1)
             ? g_trade.Buy (lot, _Symbol, 0, sl, tp, comment)
             : g_trade.Sell(lot, _Symbol, 0, sl, tp, comment);

   if(ok)
   {
      g_last_trade_bar_idx = total_bars;
      if(InpLogSignals)
         PrintFormat("[OPEN OK] %s lot=%.2f entry=%.2f SL=%.2f TP=%.2f (ATR=%.2f)",
                     m.direction == +1 ? "BUY" : "SELL", lot, entry, sl, tp, atr_i);
   }
   else
   {
      PrintFormat("[OPEN FAIL] code=%d desc=%s",
                  g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
   }
}

void ManageTrailing()
{
   if(!InpEnableTrailing) return;
   double atr_buf[1];
   if(CopyBuffer(g_atr_handle, 0, 0, 1, atr_buf) <= 0) return;
   double atr = atr_buf[0];

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Symbol() != _Symbol || g_pos.Magic() != InpMagic) continue;

      double entry = g_pos.PriceOpen();
      double sl = g_pos.StopLoss();
      double tp = g_pos.TakeProfit();
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double sl_dist = (g_pos.PositionType() == POSITION_TYPE_BUY) ? entry - sl : sl - entry;
      if(sl_dist <= 0) continue;

      if(g_pos.PositionType() == POSITION_TYPE_BUY)
      {
         double profit = bid - entry;
         if(profit < InpTrailStartR * sl_dist) continue;
         double new_sl = bid - InpTrailATR * atr;
         if(new_sl > sl + _Point) g_trade.PositionModify(g_pos.Ticket(), new_sl, tp);
      }
      else
      {
         double profit = entry - ask;
         if(profit < InpTrailStartR * sl_dist) continue;
         double new_sl = ask + InpTrailATR * atr;
         if(new_sl < sl - _Point) g_trade.PositionModify(g_pos.Ticket(), new_sl, tp);
      }
   }
}

//+------------------------------------------------------------------+
//| Detect newly closed positions to update loss streak               |
//+------------------------------------------------------------------+
void UpdateLossStreak()
{
   if(InpMaxLossStreak <= 0) return;
   if(!HistorySelect(0, TimeCurrent())) return;
   int total = HistoryDealsTotal();

   for(int i = 0; i < total; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket <= g_last_seen_deal_ticket) continue;
      if(HistoryDealGetString(ticket, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != InpMagic) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;

      double net = HistoryDealGetDouble(ticket, DEAL_PROFIT)
                 + HistoryDealGetDouble(ticket, DEAL_SWAP)
                 + HistoryDealGetDouble(ticket, DEAL_COMMISSION);

      if(net < 0) g_current_loss_streak++;
      else if(net > 0) g_current_loss_streak = 0;

      if(g_current_loss_streak >= InpMaxLossStreak)
      {
         g_loss_streak_resume_bar = Bars(_Symbol, PERIOD_CURRENT) + InpLossStreakCooldownBars;
         PrintFormat("[BREAKER] %d consecutive losses -> pause until bar %d (%d bars cooldown)",
                     g_current_loss_streak, g_loss_streak_resume_bar, InpLossStreakCooldownBars);
         g_current_loss_streak = 0;  // reset counter after triggering
      }

      g_last_seen_deal_ticket = ticket;
   }
}

void OnTick()
{
   UpdateLossStreak();
   ManageTrailing();
   if(!IsNewBar()) return;
   TryOpen();
}

//+------------------------------------------------------------------+
//| SUMMARY REPORT (printed to Journal at end of backtest)            |
//| Layout inspired by CrashHunter v6                                 |
//+------------------------------------------------------------------+
void PrintSummaryReport()
{
   if(!HistorySelect(0, TimeCurrent())) return;
   int totalDeals = HistoryDealsTotal();
   if(totalDeals == 0) return;

   // --- Per-trade aggregates ---
   int totalTrades = 0, wins = 0, losses = 0;
   double grossProfit = 0, grossLoss = 0, totalProfit = 0;
   double maxWin = 0, maxLoss = 0;
   int currentWinStreak = 0, currentLossStreak = 0;
   int maxWinStreak = 0, maxLossStreak = 0;
   double runningBalance = 0, peakBalance = 0, maxDrawdown = 0;

   // --- Per-recipe tracking (GL1-GL6 in v2) ---
   string recipeNames[6] = {"GL1", "GL2", "GL3", "GL4", "GL5", "GL6"};
   int    recipeCount[6] = {0, 0, 0, 0, 0, 0};
   int    recipeWins[6]  = {0, 0, 0, 0, 0, 0};
   double recipePnl[6]   = {0, 0, 0, 0, 0, 0};
   // Solo-recipe tracking: trades where ONLY that recipe fired (no overlap)
   int    recipeSoloCount[6] = {0, 0, 0, 0, 0, 0};
   int    recipeSoloWins[6]  = {0, 0, 0, 0, 0, 0};
   double recipeSoloPnl[6]   = {0, 0, 0, 0, 0, 0};

   // --- Exit reasons (from deal reason on the OUT side) ---
   int tpCount = 0, slCount = 0, otherCount = 0;
   double tpPnl = 0, slPnl = 0, otherPnl = 0;

   // --- Monthly breakdown ---
   int    monthKeys[];
   double monthPnl[];
   int    monthTrades[];
   int    monthWins[];
   int    numMonths = 0;

   // --- Session breakdown (hour of entry) ---
   int hourCount[24];
   double hourPnl[24];
   int hourWins[24];
   for(int h = 0; h < 24; h++) { hourCount[h] = 0; hourPnl[h] = 0; hourWins[h] = 0; }

   for(int i = 0; i < totalDeals; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(HistoryDealGetString(ticket, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != InpMagic) continue;

      ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(ticket, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_OUT) continue;

      double profit = HistoryDealGetDouble(ticket, DEAL_PROFIT);
      double swap = HistoryDealGetDouble(ticket, DEAL_SWAP);
      double commission = HistoryDealGetDouble(ticket, DEAL_COMMISSION);
      double net = profit + swap + commission;
      ENUM_DEAL_REASON reason = (ENUM_DEAL_REASON)HistoryDealGetInteger(ticket, DEAL_REASON);
      datetime exitTime = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);

      totalTrades++;
      totalProfit += net;
      runningBalance += net;
      if(runningBalance > peakBalance) peakBalance = runningBalance;
      double dd = peakBalance - runningBalance;
      if(dd > maxDrawdown) maxDrawdown = dd;

      bool isWin = (net > 0);
      if(isWin)
      {
         wins++; grossProfit += net;
         if(net > maxWin) maxWin = net;
         currentWinStreak++;
         if(currentWinStreak > maxWinStreak) maxWinStreak = currentWinStreak;
         currentLossStreak = 0;
      }
      else
      {
         losses++; grossLoss += MathAbs(net);
         if(net < maxLoss) maxLoss = net;
         currentLossStreak++;
         if(currentLossStreak > maxLossStreak) maxLossStreak = currentLossStreak;
         currentWinStreak = 0;
      }

      // Exit reason
      if(reason == DEAL_REASON_TP)      { tpCount++; tpPnl += net; }
      else if(reason == DEAL_REASON_SL) { slCount++; slPnl += net; }
      else                              { otherCount++; otherPnl += net; }

      // --- Find the opening deal for this position (for comment + entry time) ---
      ulong posId = HistoryDealGetInteger(ticket, DEAL_POSITION_ID);
      string entryComment = "";
      datetime entryTime = 0;
      for(int j = 0; j < totalDeals; j++)
      {
         ulong t2 = HistoryDealGetTicket(j);
         if(HistoryDealGetInteger(t2, DEAL_POSITION_ID) == posId &&
            (ENUM_DEAL_ENTRY)HistoryDealGetInteger(t2, DEAL_ENTRY) == DEAL_ENTRY_IN)
         {
            entryComment = HistoryDealGetString(t2, DEAL_COMMENT);
            entryTime = (datetime)HistoryDealGetInteger(t2, DEAL_TIME);
            break;
         }
      }

      // Recipe parsing
      int matchedCount = 0;
      bool present[6] = {false, false, false, false, false, false};
      for(int r = 0; r < 6; r++)
      {
         if(StringFind(entryComment, recipeNames[r]) >= 0)
         {
            present[r] = true;
            matchedCount++;
            recipeCount[r]++;
            recipePnl[r] += net;
            if(isWin) recipeWins[r]++;
         }
      }
      if(matchedCount == 1)
      {
         for(int r = 0; r < 6; r++)
         {
            if(present[r])
            {
               recipeSoloCount[r]++;
               recipeSoloPnl[r] += net;
               if(isWin) recipeSoloWins[r]++;
            }
         }
      }

      // Monthly
      MqlDateTime dt; TimeToStruct(exitTime, dt);
      int monthKey = dt.year * 100 + dt.mon;
      int mIdx = -1;
      for(int m = 0; m < numMonths; m++) if(monthKeys[m] == monthKey) { mIdx = m; break; }
      if(mIdx == -1)
      {
         numMonths++;
         ArrayResize(monthKeys, numMonths);
         ArrayResize(monthPnl, numMonths);
         ArrayResize(monthTrades, numMonths);
         ArrayResize(monthWins, numMonths);
         mIdx = numMonths - 1;
         monthKeys[mIdx] = monthKey;
         monthPnl[mIdx] = 0; monthTrades[mIdx] = 0; monthWins[mIdx] = 0;
      }
      monthPnl[mIdx] += net;
      monthTrades[mIdx]++;
      if(isWin) monthWins[mIdx]++;

      // Hour of entry
      if(entryTime > 0)
      {
         MqlDateTime edt; TimeToStruct(entryTime, edt);
         int h = edt.hour;
         if(h >= 0 && h < 24)
         {
            hourCount[h]++;
            hourPnl[h] += net;
            if(isWin) hourWins[h]++;
         }
      }
   }

   if(totalTrades == 0) return;

   double winRate = (double)wins / totalTrades * 100.0;
   double pf = (grossLoss > 0) ? grossProfit / grossLoss : 99;
   double avgWin = (wins > 0) ? grossProfit / wins : 0;
   double avgLoss = (losses > 0) ? grossLoss / losses : 0;
   double expectancy = (winRate/100.0 * avgWin) - ((100.0-winRate)/100.0 * avgLoss);
   double initBal = TesterStatistics(STAT_INITIAL_DEPOSIT);
   double retPct = (initBal > 0) ? totalProfit / initBal * 100.0 : 0;
   double rrRealized = (avgLoss > 0) ? avgWin / avgLoss : 0;

   Print("======================================================================");
   Print("  GOLD BEHAVIOR EA v2.00 - BACKTEST SUMMARY REPORT");
   Print("======================================================================");
   Print("");
   Print("--- PERFORMANCE ---");
   Print("  Initial Balance:    $", DoubleToString(initBal, 2));
   Print("  Final Balance:      $", DoubleToString(initBal + totalProfit, 2));
   Print("  Net Profit:         $", DoubleToString(totalProfit, 2));
   Print("  Return:             ", DoubleToString(retPct, 2), "%");
   Print("  Max Drawdown:       $", DoubleToString(maxDrawdown, 2));
   Print("  Profit Factor:      ", DoubleToString(pf, 2));
   Print("  Expectancy/trade:   $", DoubleToString(expectancy, 2));
   Print("");
   Print("--- TRADES ---");
   Print("  Total Trades:       ", totalTrades);
   Print("  Winners:            ", wins, " (", DoubleToString(winRate, 1), "%)");
   Print("  Losers:             ", losses, " (", DoubleToString(100-winRate, 1), "%)");
   Print("  Avg Winner:         $", DoubleToString(avgWin, 2));
   Print("  Avg Loser:          $", DoubleToString(avgLoss, 2));
   Print("  Best Trade:         $", DoubleToString(maxWin, 2));
   Print("  Worst Trade:        $", DoubleToString(maxLoss, 2));
   Print("  Max Win Streak:     ", maxWinStreak);
   Print("  Max Loss Streak:    ", maxLossStreak);
   Print("  Realized R:R:       1:", DoubleToString(rrRealized, 2));
   Print("");
   Print("--- EXIT REASONS ---");
   Print("  Take Profit:    ", tpCount, " trades | $", DoubleToString(tpPnl, 2));
   Print("  Stop Loss:      ", slCount, " trades | $", DoubleToString(slPnl, 2));
   Print("  Trailing/Other: ", otherCount, " trades | $", DoubleToString(otherPnl, 2));
   Print("");

   // --- Per-recipe report (sorted by PnL desc) ---
   Print("--- RECIPE PERFORMANCE (all trades involving the recipe) ---");
   int order[6] = {0, 1, 2, 3, 4, 5};
   for(int a = 0; a < 5; a++)
      for(int b = a + 1; b < 6; b++)
         if(recipePnl[order[b]] > recipePnl[order[a]])
         { int tmp = order[a]; order[a] = order[b]; order[b] = tmp; }

   for(int k = 0; k < 6; k++)
   {
      int r = order[k];
      if(recipeCount[r] == 0) continue;
      double rw = (double)recipeWins[r] / recipeCount[r] * 100.0;
      double ra = recipePnl[r] / recipeCount[r];
      string marker = (recipePnl[r] > 0) ? "PROFIT" : "LOSS";
      Print("  ", recipeNames[r],
            "  n=", recipeCount[r],
            " | WR=", DoubleToString(rw, 1), "%",
            " | PnL=$", DoubleToString(recipePnl[r], 2),
            " | Avg=$", DoubleToString(ra, 2),
            "  [", marker, "]");
   }
   Print("");
   Print("--- RECIPE PERFORMANCE (SOLO - recipe fired alone) ---");
   for(int k = 0; k < 6; k++)
   {
      int r = order[k];
      if(recipeSoloCount[r] == 0) { Print("  ", recipeNames[r], "  n=0 (never solo)"); continue; }
      double rw = (double)recipeSoloWins[r] / recipeSoloCount[r] * 100.0;
      double ra = recipeSoloPnl[r] / recipeSoloCount[r];
      string marker = (recipeSoloPnl[r] > 0) ? "PROFIT" : "LOSS";
      Print("  ", recipeNames[r],
            "  n=", recipeSoloCount[r],
            " | WR=", DoubleToString(rw, 1), "%",
            " | PnL=$", DoubleToString(recipeSoloPnl[r], 2),
            " | Avg=$", DoubleToString(ra, 2),
            "  [", marker, "]");
   }
   Print("");

   // --- Monthly breakdown (chronological) ---
   // bubble-sort monthKeys ascending
   for(int a = 0; a < numMonths - 1; a++)
      for(int b = a + 1; b < numMonths; b++)
         if(monthKeys[b] < monthKeys[a])
         {
            int tmpK = monthKeys[a]; monthKeys[a] = monthKeys[b]; monthKeys[b] = tmpK;
            double tmpP = monthPnl[a]; monthPnl[a] = monthPnl[b]; monthPnl[b] = tmpP;
            int tmpT = monthTrades[a]; monthTrades[a] = monthTrades[b]; monthTrades[b] = tmpT;
            int tmpW = monthWins[a]; monthWins[a] = monthWins[b]; monthWins[b] = tmpW;
         }

   Print("--- MONTHLY BREAKDOWN ---");
   int profitableMonths = 0;
   double cumul = initBal;
   for(int m = 0; m < numMonths; m++)
   {
      int yr = monthKeys[m] / 100;
      int mn = monthKeys[m] % 100;
      double mwr = (monthTrades[m] > 0) ? (double)monthWins[m] / monthTrades[m] * 100.0 : 0;
      cumul += monthPnl[m];
      string marker = (monthPnl[m] > 0) ? "+" : (monthPnl[m] < 0 ? "-" : "=");
      Print("  ", yr, "-", (mn < 10 ? "0" : ""), mn,
            " | PnL=$", DoubleToString(monthPnl[m], 2),
            " | trades=", monthTrades[m],
            " | WR=", DoubleToString(mwr, 0), "%",
            " | bal=$", DoubleToString(cumul, 2),
            "  ", marker);
      if(monthPnl[m] > 0) profitableMonths++;
   }
   Print("  Profitable Months:  ", profitableMonths, "/", numMonths,
         " (", DoubleToString((double)profitableMonths/MathMax(1,numMonths)*100.0, 0), "%)");
   Print("");

   // --- Hour of entry breakdown ---
   Print("--- HOUR OF ENTRY (UTC) BREAKDOWN ---");
   for(int h = 0; h < 24; h++)
   {
      if(hourCount[h] == 0) continue;
      double hwr = (double)hourWins[h] / hourCount[h] * 100.0;
      double havg = hourPnl[h] / hourCount[h];
      Print("  ", (h < 10 ? "0" : ""), h, "h:",
            " n=", hourCount[h],
            " | WR=", DoubleToString(hwr, 0), "%",
            " | PnL=$", DoubleToString(hourPnl[h], 2),
            " | Avg=$", DoubleToString(havg, 2));
   }
   Print("");
   Print("--- SETTINGS USED ---");
   Print("  Risk per trade:   ", DoubleToString(InpRiskPercent, 2), "%");
   Print("  Fixed lot:        ", DoubleToString(InpFixedLot, 2), " (0 = risk-based)");
   Print("  TP / SL ATR:      ", DoubleToString(InpTPatATR, 1), " / ", DoubleToString(InpSLatATR, 1));
   Print("  Max spread:       ", InpMaxSpreadPoints, " pts");
   Print("  Cooldown bars:    ", InpCooldownBars);
   Print("  Max positions:    ", InpMaxPositions);
   Print("  Pctile window:    ", InpPercentileWindow, " bars");
   Print("  Trailing:         ", InpEnableTrailing ? "ON" : "OFF",
         "  start=", DoubleToString(InpTrailStartR, 1), "R",
         "  dist=", DoubleToString(InpTrailATR, 1), "xATR");
   Print("  Recipes:          ",
         "GL1=", InpEnableGL1 ? "Y" : "N",
         " GL2=", InpEnableGL2 ? "Y" : "N",
         " GL3=", InpEnableGL3 ? "Y" : "N",
         " GL4=", InpEnableGL4 ? "Y" : "N",
         " GL5=", InpEnableGL5 ? "Y" : "N",
         " GL6=", InpEnableGL6 ? "Y" : "N",
         "  GL3-conf-req=", InpGL3RequireConfluence ? "Y" : "N");
   string blocked_hours = "";
   for(int h = 0; h < 24; h++) if(g_hour_blocked[h]) blocked_hours += IntegerToString(h) + " ";
   Print("  Forbidden hours:  ", blocked_hours == "" ? "(none)" : blocked_hours);
   if(InpMaxLossStreak > 0)
      Print("  Loss-streak stop: ", InpMaxLossStreak, " losses, cooldown ", InpLossStreakCooldownBars, " bars");
   Print("  Regime filter:    EMA200-slope=", InpUseEMA200Slope ? "ON" : "OFF",
         " (", InpEMA200SlopeBars, "b), ADX=", InpUseADXFilter ? "ON" : "OFF",
         " (>=", DoubleToString(InpADXMin, 1), ")");
   Print("");
   Print("======================================================================");
   Print("  Copy everything above and paste into the chat for analysis");
   Print("======================================================================");
}

//+------------------------------------------------------------------+
//| OnTester: custom optimization criterion (PF * sqrt(trades))       |
//+------------------------------------------------------------------+
double OnTester()
{
   double pf = TesterStatistics(STAT_PROFIT_FACTOR);
   int n = (int)TesterStatistics(STAT_TRADES);
   double dd = TesterStatistics(STAT_EQUITY_DDREL_PERCENT);
   if(n < 20) return 0;  // too few trades
   double score = pf * MathSqrt(n) - dd * 0.1;
   return score;
}
//+------------------------------------------------------------------+
