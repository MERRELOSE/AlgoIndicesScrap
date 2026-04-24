//+------------------------------------------------------------------+
//|                                              Behavior_EA_v1.mq5   |
//|                       Behavioral recipe EA for EURUSD H1          |
//|                       AlgoIndicesScrap Project                    |
//+------------------------------------------------------------------+
//  Auto-trader based on behavioral recipes discovered by the Python
//  pipeline (forex/run_behavior.py) on EURUSD H1, 5 years.
//
//  Validated out-of-sample (2024-2026 data):
//    LONG recipes  base rate 31%:
//      L1: atr_ratio_q2 + bb_pos_q1 + h_1              → OOS WR 45.6% (lift 1.47)
//      L2: atr_ratio_q2 + sess_overlap + streak_down_34 → OOS WR 45.2% (lift 1.45)
//      L3: atr_14_q2    + dow_0       + streak_down_34 → OOS WR 41.7% (lift 1.34)
//
//    SHORT recipes base rate 9%:
//      S1: dow_3 + h_2 + vol_5_20_q3                   → OOS WR 20.9% (lift 2.52)
//      S2: dist_ema200_q3 + dow_3 + h_2                → OOS WR 19.7% (lift 2.38)
//      S3: bb_width_q1 + h_1 + pos_in_range_20_q1      → OOS WR 18.8% (lift 2.26)
//
//  Exit: TP = 2×ATR, SL = 1×ATR (R:R 2:1). Breakeven WR = 33.3%.
//+------------------------------------------------------------------+
#property copyright "AlgoIndicesScrap"
#property version   "1.00"
#property description "EURUSD H1 behavioral-recipe trader. R:R 2:1."
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//+------------------------------------------------------------------+
//| INPUTS                                                            |
//+------------------------------------------------------------------+
input group "=== Risk ==="
input double InpRiskPercent      = 1.0;    // Risk per trade (% equity)
input double InpFixedLot         = 0.0;    // Fixed lot (0 = use risk %)
input double InpTPatATR          = 2.0;    // TP distance in ATR
input double InpSLatATR          = 1.0;    // SL distance in ATR
input int    InpMaxSpreadPoints  = 30;     // Skip entry if spread > this points
input int    InpMagic            = 770002;

input group "=== Recipes enable ==="
input bool   InpEnableLong1      = true;   // L1: atr_ratio_q2 + bb_pos_q1 + h_1
input bool   InpEnableLong2      = true;   // L2: atr_ratio_q2 + sess_overlap + streak_down_34
input bool   InpEnableLong3      = true;   // L3: atr_14_q2 + Monday + streak_down_34
input bool   InpEnableShort1     = true;   // S1: dow_3(Thu) + h_2 + vol_5_20_q3
input bool   InpEnableShort2     = true;   // S2: dist_ema200_q3 + dow_3 + h_2
input bool   InpEnableShort3     = true;   // S3: bb_width_q1 + h_1 + pos_in_range_20_q1

input group "=== Indicator periods ==="
input int    InpATRPeriod        = 14;
input int    InpATRLongPeriod    = 100;
input int    InpBBPeriod         = 20;
input double InpBBStd            = 2.0;
input int    InpEMA200Period     = 200;
input int    InpPercentileWindow = 500;   // Rolling window for percentile bins

input group "=== Trade mgmt ==="
input int    InpCooldownBars     = 3;     // Min bars between trades
input bool   InpEnableTrailing   = false; // Trail SL after 1R hit
input double InpTrailATR         = 1.0;

//+------------------------------------------------------------------+
//| GLOBALS                                                           |
//+------------------------------------------------------------------+
CTrade         g_trade;
CPositionInfo  g_pos;
int            g_atr_handle = INVALID_HANDLE;
int            g_atr_long_handle = INVALID_HANDLE;
int            g_bb_handle = INVALID_HANDLE;
int            g_ema200_handle = INVALID_HANDLE;
datetime       g_last_bar = 0;
int            g_last_trade_bar_idx = -9999;

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_trade.SetMarginMode();
   g_trade.SetDeviationInPoints(10);

   g_atr_handle      = iATR(_Symbol, PERIOD_CURRENT, InpATRPeriod);
   g_atr_long_handle = iATR(_Symbol, PERIOD_CURRENT, InpATRLongPeriod);
   g_bb_handle       = iBands(_Symbol, PERIOD_CURRENT, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE);
   g_ema200_handle   = iMA(_Symbol, PERIOD_CURRENT, InpEMA200Period, 0, MODE_EMA, PRICE_CLOSE);

   if(g_atr_handle == INVALID_HANDLE || g_atr_long_handle == INVALID_HANDLE ||
      g_bb_handle == INVALID_HANDLE || g_ema200_handle == INVALID_HANDLE)
   {
      Print("Failed to init indicator handles");
      return INIT_FAILED;
   }
   PrintFormat("Behavior EA init: magic=%d RR=%.1f:%.1f risk=%.2f%%",
               InpMagic, InpTPatATR, InpSLatATR, InpRiskPercent);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(g_atr_handle != INVALID_HANDLE) IndicatorRelease(g_atr_handle);
   if(g_atr_long_handle != INVALID_HANDLE) IndicatorRelease(g_atr_long_handle);
   if(g_bb_handle != INVALID_HANDLE) IndicatorRelease(g_bb_handle);
   if(g_ema200_handle != INVALID_HANDLE) IndicatorRelease(g_ema200_handle);
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

bool HasOpenForMagic()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(g_pos.SelectByIndex(i) && g_pos.Symbol() == _Symbol && g_pos.Magic() == InpMagic)
         return true;
   }
   return false;
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

double CalcLotByRisk(double sl_price_distance)
{
   if(InpFixedLot > 0) return NormalizeLot(InpFixedLot);
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk = eq * InpRiskPercent / 100.0;
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(ts <= 0 || tv <= 0 || sl_price_distance <= 0) return NormalizeLot(0.01);
   double loss_per_lot = (sl_price_distance / ts) * tv;
   if(loss_per_lot <= 0) return NormalizeLot(0.01);
   return NormalizeLot(risk / loss_per_lot);
}

//+------------------------------------------------------------------+
//| Rolling percentile rank of `value` within `series[start..start+N]`|
//| Returns rank in [0, 1]. N typically InpPercentileWindow.          |
//+------------------------------------------------------------------+
double PercentileRank(const double &series[], int start, int N, double value)
{
   if(N < 10) return 0.5;
   int count = 0;
   int n_valid = 0;
   for(int i = start; i < start + N; i++)
   {
      double v = series[i];
      if(v == EMPTY_VALUE || v == 0.0 && value != 0.0) continue;
      n_valid++;
      if(v <= value) count++;
   }
   if(n_valid == 0) return 0.5;
   return (double)count / n_valid;
}

//+------------------------------------------------------------------+
//| Fetch data arrays (as-series: 0 = current)                        |
//+------------------------------------------------------------------+
bool GetArrays(double &highs[], double &lows[], double &closes[], double &opens[],
               double &atrs[], double &atrs_long[], double &bb_up[], double &bb_lo[], double &bb_mid[],
               double &ema200[], int count)
{
   if(CopyHigh (_Symbol, PERIOD_CURRENT, 0, count, highs)  <= 0) return false;
   if(CopyLow  (_Symbol, PERIOD_CURRENT, 0, count, lows)   <= 0) return false;
   if(CopyClose(_Symbol, PERIOD_CURRENT, 0, count, closes) <= 0) return false;
   if(CopyOpen (_Symbol, PERIOD_CURRENT, 0, count, opens)  <= 0) return false;
   if(CopyBuffer(g_atr_handle,      0, 0, count, atrs)      <= 0) return false;
   if(CopyBuffer(g_atr_long_handle, 0, 0, count, atrs_long) <= 0) return false;
   if(CopyBuffer(g_bb_handle,       1, 0, count, bb_up)     <= 0) return false; // UPPER
   if(CopyBuffer(g_bb_handle,       2, 0, count, bb_lo)     <= 0) return false; // LOWER
   if(CopyBuffer(g_bb_handle,       0, 0, count, bb_mid)    <= 0) return false; // MIDDLE
   if(CopyBuffer(g_ema200_handle,   0, 0, count, ema200)    <= 0) return false;
   return true;
}

//+------------------------------------------------------------------+
//| Streak helpers                                                    |
//+------------------------------------------------------------------+
int CountConsecDown(const double &opens[], const double &closes[])
{
   int c = 0;
   for(int i = 1; i < 30; i++)
   {
      if(closes[i] < opens[i]) c++;
      else break;
   }
   return c;
}
int CountConsecUp(const double &opens[], const double &closes[])
{
   int c = 0;
   for(int i = 1; i < 30; i++)
   {
      if(closes[i] > opens[i]) c++;
      else break;
   }
   return c;
}

//+------------------------------------------------------------------+
//| Condition helpers — each returns bool                             |
//| "q1" quartile 1 = pctile <= 0.25 ; "q2" = (0.25, 0.50] ;          |
//| "q3" = (0.50, 0.75] ; "q4" = (0.75, 1.00]                         |
//+------------------------------------------------------------------+
bool ConditionSet(int &hour_out, int &dow_out,
                  bool &cond_atr14_q2, bool &cond_atr_ratio_q2, bool &cond_atr_ratio_q1,
                  bool &cond_bb_pos_q1, bool &cond_bb_width_q1,
                  bool &cond_vol5_20_q3, bool &cond_pos_range_q1, bool &cond_dist_ema200_q3,
                  bool &cond_streak_down_34, bool &cond_sess_overlap,
                  bool &cond_hour_1, bool &cond_hour_2, bool &cond_hour_3,
                  bool &cond_dow_0, bool &cond_dow_3, bool &cond_dow_4)
{
   int need = InpPercentileWindow + 50;
   double H[], L[], C[], O[], A[], AL[], BU[], BD[], BM[], E200[];
   ArraySetAsSeries(H, true); ArraySetAsSeries(L, true); ArraySetAsSeries(C, true);
   ArraySetAsSeries(O, true); ArraySetAsSeries(A, true); ArraySetAsSeries(AL, true);
   ArraySetAsSeries(BU, true); ArraySetAsSeries(BD, true); ArraySetAsSeries(BM, true);
   ArraySetAsSeries(E200, true);
   if(!GetArrays(H, L, C, O, A, AL, BU, BD, BM, E200, need)) return false;

   // Current bar (index 1 = last closed bar, index 0 = live bar)
   int i = 1;  // we decide on the last closed bar
   double atr_i = A[i];
   double atr_l_i = AL[i];
   if(atr_i <= 0 || atr_l_i <= 0) return false;

   double close_i = C[i];
   double bb_u = BU[i], bb_d = BD[i];
   double bb_width_raw = (bb_u - bb_d) / BM[i];
   double bb_pos_raw = (close_i - bb_d) / (bb_u - bb_d + 1e-12);
   double atr_ratio_raw = atr_i / atr_l_i;
   double dist_ema200_raw = (close_i - E200[i]) / close_i;

   // pos_in_range_20: close_i relative to 20-bar high/low
   double hi20 = H[ArrayMaximum(H, i, 20)];
   double lo20 = L[ArrayMinimum(L, i, 20)];
   double pos_range = (close_i - lo20) / (hi20 - lo20 + 1e-12);

   // vol_5_20: std(ret_5) / std(ret_20)
   double rets[30];
   for(int k = 0; k < 25; k++)
      rets[k] = (C[i + k] - C[i + k + 1]) / C[i + k + 1];
   double m5 = 0, m20 = 0;
   for(int k = 0; k < 5; k++) m5 += rets[k];
   m5 /= 5;
   for(int k = 0; k < 20; k++) m20 += rets[k];
   m20 /= 20;
   double v5 = 0, v20 = 0;
   for(int k = 0; k < 5; k++) v5 += MathPow(rets[k] - m5, 2);
   v5 = MathSqrt(v5 / 5);
   for(int k = 0; k < 20; k++) v20 += MathPow(rets[k] - m20, 2);
   v20 = MathSqrt(v20 / 20);
   double vol_5_20_raw = (v20 > 0) ? v5 / v20 : 1.0;

   // Build rolling series for percentile computation (over InpPercentileWindow bars)
   double ser_atr14[], ser_atr_ratio[], ser_bb_pos[], ser_bb_width[],
          ser_pos_range[], ser_vol_5_20[], ser_dist_ema200[];
   ArrayResize(ser_atr14, InpPercentileWindow);
   ArrayResize(ser_atr_ratio, InpPercentileWindow);
   ArrayResize(ser_bb_pos, InpPercentileWindow);
   ArrayResize(ser_bb_width, InpPercentileWindow);
   ArrayResize(ser_pos_range, InpPercentileWindow);
   ArrayResize(ser_vol_5_20, InpPercentileWindow);
   ArrayResize(ser_dist_ema200, InpPercentileWindow);

   for(int k = 0; k < InpPercentileWindow; k++)
   {
      int j = i + k;
      ser_atr14[k]       = A[j];
      ser_atr_ratio[k]   = (AL[j] > 0) ? A[j] / AL[j] : 1.0;
      ser_bb_pos[k]      = (BU[j] - BD[j] > 0) ? (C[j] - BD[j]) / (BU[j] - BD[j]) : 0.5;
      ser_bb_width[k]    = (BM[j] > 0) ? (BU[j] - BD[j]) / BM[j] : 0.0;
      double hi_k = H[ArrayMaximum(H, j, 20)];
      double lo_k = L[ArrayMinimum(L, j, 20)];
      ser_pos_range[k]   = (hi_k - lo_k > 0) ? (C[j] - lo_k) / (hi_k - lo_k) : 0.5;
      ser_dist_ema200[k] = (C[j] - E200[j]) / C[j];

      // vol_5_20 series — heavy: just use simple approximation via bar ranges
      // (quicker than recomputing full return std for every bar). Use (H-L)/C ratio.
      double rng_5 = 0, rng_20 = 0;
      int kk_end_5 = MathMin(j + 5, need);
      int kk_end_20 = MathMin(j + 20, need);
      for(int kk = j; kk < kk_end_5; kk++) rng_5 += (H[kk] - L[kk]) / C[kk];
      for(int kk = j; kk < kk_end_20; kk++) rng_20 += (H[kk] - L[kk]) / C[kk];
      rng_5 /= 5.0; rng_20 /= 20.0;
      ser_vol_5_20[k] = (rng_20 > 0) ? rng_5 / rng_20 : 1.0;
   }

   // Compute percentile rank of current value
   double pr_atr14       = PercentileRank(ser_atr14,       0, InpPercentileWindow, atr_i);
   double pr_atr_ratio   = PercentileRank(ser_atr_ratio,   0, InpPercentileWindow, atr_ratio_raw);
   double pr_bb_pos      = PercentileRank(ser_bb_pos,      0, InpPercentileWindow, bb_pos_raw);
   double pr_bb_width    = PercentileRank(ser_bb_width,    0, InpPercentileWindow, bb_width_raw);
   double pr_pos_range   = PercentileRank(ser_pos_range,   0, InpPercentileWindow, pos_range);
   double pr_vol_5_20    = PercentileRank(ser_vol_5_20,    0, InpPercentileWindow, vol_5_20_raw);
   double pr_dist_ema200 = PercentileRank(ser_dist_ema200, 0, InpPercentileWindow, dist_ema200_raw);

   // Quartile conditions
   cond_atr14_q2       = (pr_atr14       > 0.25 && pr_atr14       <= 0.50);
   cond_atr_ratio_q2   = (pr_atr_ratio   > 0.25 && pr_atr_ratio   <= 0.50);
   cond_atr_ratio_q1   = (pr_atr_ratio   <= 0.25);
   cond_bb_pos_q1      = (pr_bb_pos      <= 0.25);
   cond_bb_width_q1    = (pr_bb_width    <= 0.25);
   cond_vol5_20_q3     = (pr_vol_5_20    > 0.50 && pr_vol_5_20    <= 0.75);
   cond_pos_range_q1   = (pr_pos_range   <= 0.25);
   cond_dist_ema200_q3 = (pr_dist_ema200 > 0.50 && pr_dist_ema200 <= 0.75);

   // Streak
   int consec_down = CountConsecDown(O, C);
   cond_streak_down_34 = (consec_down >= 3 && consec_down <= 4);

   // Time features (hour in UTC, dow)
   MqlDateTime mdt;
   TimeToStruct(iTime(_Symbol, PERIOD_CURRENT, i), mdt);
   hour_out = mdt.hour;
   dow_out = mdt.day_of_week;  // 0=Sunday, 1=Monday,... in MQL5

   // Map hour to bucket (h_0..h_5, each = 4h)
   int hour_bucket = hour_out / 4;
   cond_hour_1 = (hour_bucket == 1);   // hours 4-7 UTC
   cond_hour_2 = (hour_bucket == 2);   // hours 8-11 UTC
   cond_hour_3 = (hour_bucket == 3);   // hours 12-15 UTC

   // Session overlap London/NY = hours 12-15 UTC approximately
   cond_sess_overlap = (hour_out >= 12 && hour_out < 16);

   // Day of week: Python's dayofweek is 0=Monday. MT5 day_of_week: 0=Sunday.
   // Convert to Python convention: 0=Mon, 1=Tue, ..., 4=Fri
   // MT5: 0=Sun, 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat
   int dow_py = (dow_out == 0) ? 6 : dow_out - 1;
   cond_dow_0 = (dow_py == 0);  // Monday
   cond_dow_3 = (dow_py == 3);  // Thursday
   cond_dow_4 = (dow_py == 4);  // Friday

   return true;
}

//+------------------------------------------------------------------+
//| Try to open based on recipe matching                              |
//+------------------------------------------------------------------+
void TryOpen()
{
   int total_bars = Bars(_Symbol, PERIOD_CURRENT);
   if(total_bars - g_last_trade_bar_idx < InpCooldownBars) return;

   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > InpMaxSpreadPoints) return;

   int hour, dow;
   bool atr14_q2, atr_ratio_q2, atr_ratio_q1;
   bool bb_pos_q1, bb_width_q1;
   bool vol5_20_q3, pos_range_q1, dist_ema200_q3;
   bool streak_down_34, sess_overlap;
   bool h1, h2, h3, dow0, dow3, dow4;

   if(!ConditionSet(hour, dow,
                    atr14_q2, atr_ratio_q2, atr_ratio_q1,
                    bb_pos_q1, bb_width_q1,
                    vol5_20_q3, pos_range_q1, dist_ema200_q3,
                    streak_down_34, sess_overlap,
                    h1, h2, h3, dow0, dow3, dow4))
      return;

   // Evaluate each recipe
   bool L1 = InpEnableLong1  && atr_ratio_q2 && bb_pos_q1    && h1;
   bool L2 = InpEnableLong2  && atr_ratio_q2 && sess_overlap && streak_down_34;
   bool L3 = InpEnableLong3  && atr14_q2     && dow0         && streak_down_34;
   bool S1 = InpEnableShort1 && dow3         && h2           && vol5_20_q3;
   bool S2 = InpEnableShort2 && dist_ema200_q3 && dow3       && h2;
   bool S3 = InpEnableShort3 && bb_width_q1 && h1            && pos_range_q1;

   int direction = 0;
   string matched = "";
   if(L1 || L2 || L3) { direction = +1; matched = (L1?"L1 ":"") + (L2?"L2 ":"") + (L3?"L3":""); }
   else if(S1 || S2 || S3) { direction = -1; matched = (S1?"S1 ":"") + (S2?"S2 ":"") + (S3?"S3":""); }

   if(direction == 0) return;

   double atr_buf[1];
   if(CopyBuffer(g_atr_handle, 0, 1, 1, atr_buf) <= 0) return;
   double atr_i = atr_buf[0];
   if(atr_i <= 0) return;

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   double entry, sl, tp;
   if(direction == +1)
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

   string comment = "Behavior " + matched;
   bool ok = (direction == +1)
             ? g_trade.Buy (lot, _Symbol, 0, sl, tp, comment)
             : g_trade.Sell(lot, _Symbol, 0, sl, tp, comment);

   if(ok)
   {
      g_last_trade_bar_idx = total_bars;
      PrintFormat("OPEN %s lot=%.2f entry=%.5f SL=%.5f TP=%.5f | %s",
                  direction == +1 ? "BUY" : "SELL", lot, entry, sl, tp, comment);
   }
   else
   {
      PrintFormat("Trade.Open failed: %d %s",
                  g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
   }
}

//+------------------------------------------------------------------+
//| Trailing stop after 1R profit                                     |
//+------------------------------------------------------------------+
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

      double sl_dist_orig = (g_pos.PositionType() == POSITION_TYPE_BUY) ? entry - sl : sl - entry;
      if(sl_dist_orig <= 0) continue;

      if(g_pos.PositionType() == POSITION_TYPE_BUY)
      {
         double profit = bid - entry;
         if(profit < sl_dist_orig) continue;
         double new_sl = bid - InpTrailATR * atr;
         if(new_sl > sl + _Point) g_trade.PositionModify(g_pos.Ticket(), new_sl, tp);
      }
      else
      {
         double profit = entry - ask;
         if(profit < sl_dist_orig) continue;
         double new_sl = ask + InpTrailATR * atr;
         if(new_sl < sl - _Point) g_trade.PositionModify(g_pos.Ticket(), new_sl, tp);
      }
   }
}

//+------------------------------------------------------------------+
//| OnTick                                                            |
//+------------------------------------------------------------------+
void OnTick()
{
   ManageTrailing();
   if(!IsNewBar()) return;
   if(HasOpenForMagic()) return;
   TryOpen();
}
//+------------------------------------------------------------------+
