//+------------------------------------------------------------------+
//|                                  WeekendGap_EA_v2_ML.mq5          |
//|         Weekend-gap trader with ONNX-classifier filtering         |
//|                       AlgoIndicesScrap Project                    |
//+------------------------------------------------------------------+
//  v2 = v1 (Friday continuation, 19:15 UTC entry, 22:15 UTC exit)
//       PLUS LightGBM ONNX model gating: only trade when proba_up >= threshold.
//
//  IMPORTANT: copy `forex/models/weekend_gap.onnx` into MT5's MQL5/Files/
//  before running. Path is typically:
//     %APPDATA%\MetaQuotes\Terminal\<HASH>\MQL5\Files\weekend_gap.onnx
//
//  Feature order (must match Python training - see forex/models/feature_names.txt):
//     0..18 : numeric features
//     19..21: sym_XAGEUR, sym_XAGUSD, sym_XAUUSD (one-hot, alphabetical)
//+------------------------------------------------------------------+
#property copyright "AlgoIndicesScrap"
#property version   "2.00"
#property description "Weekend gap EA v2 - ML-gated entries (LightGBM ONNX classifier)."
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//+------------------------------------------------------------------+
//| INPUTS                                                            |
//+------------------------------------------------------------------+
input group "=== Risk / Sizing ==="
input double InpFixedLot        = 0.01;
input double InpRiskPercent     = 0.0;
input double InpTPPercent       = 0.0;
input int    InpMagic           = 790020;   // v2 magic (different from v1)

input group "=== ML model ==="
input string InpOnnxFile        = "weekend_gap.onnx";  // located in MQL5/Files/
input double InpProbaThreshold  = 0.55;     // trade only if proba_up >= this
input bool   InpLogFeatures     = true;     // print feature vector + proba on each attempt

input group "=== Strategy ==="
input string InpStrategy        = "auto";   // auto / continuation / fade

input group "=== Broker timezone ==="
input int    InpBrokerGMTOffset = 0;        // Deriv = 0 (server is UTC)

//+------------------------------------------------------------------+
//| HARDCODED                                                         |
//+------------------------------------------------------------------+
#define FIXED_SL_PCT          0.5
#define FIXED_MIN_BODY_PCT    1.00      // pre-filter even before ML
#define FIXED_LOOKBACK_H      20
#define FIXED_LONG_ONLY       true

#define FIXED_MARKET_DST      true
#define FIXED_ENTRY_DOW       5
#define FIXED_ENTRY_HOUR_UTC  19
#define FIXED_ENTRY_MIN_UTC   15
#define FIXED_ENTRY_WIN_MIN   45
#define FIXED_EXIT_DOW        0
#define FIXED_EXIT_HOUR_UTC   22
#define FIXED_EXIT_MIN_UTC    15
#define FIXED_EXIT_WIN_MIN    60

#define N_FEATURES            22
#define ATR_PCTILE_WINDOW     60

input group "=== Safety ==="
input int    InpMaxSpreadPtsEntry = 50;
input int    InpMaxSpreadPtsExit  = 500;

input group "=== Logging ==="
input bool   InpLogEachWeekend  = true;
input bool   InpPrintSummary    = true;

//+------------------------------------------------------------------+
//| GLOBALS                                                           |
//+------------------------------------------------------------------+
CTrade        g_trade;
CPositionInfo g_pos;

string  g_resolved_strategy = "continuation";
double  g_point  = 0.0;
int     g_digits = 0;
string  g_symbol_class = "unknown";

// Indicator handles (H1 / D1)
int g_h_rsi_h1   = INVALID_HANDLE;
int g_h_atr_h1   = INVALID_HANDLE;
int g_h_ema_h1   = INVALID_HANDLE;
int g_h_atr_d1   = INVALID_HANDLE;

// ONNX
long g_onnx_handle = INVALID_HANDLE;

// State
datetime g_last_entry_attempt = 0;
datetime g_last_exit_attempt  = 0;

// Diagnostic counters
int g_ticks_in_entry_window = 0;
int g_ticks_in_exit_window  = 0;
int g_entry_attempts        = 0;
int g_entry_skipped_spread  = 0;
int g_entry_skipped_body    = 0;
int g_entry_skipped_dir     = 0;
int g_entry_skipped_proba   = 0;
int g_entry_skipped_feat    = 0;
int g_entry_opened          = 0;
int g_exits_triggered       = 0;
datetime g_first_friday_seen = 0;
datetime g_last_friday_seen  = 0;
double   g_proba_min = 1.0;
double   g_proba_max = 0.0;
double   g_proba_sum = 0.0;
int      g_proba_count = 0;

//+------------------------------------------------------------------+
//| Symbol classification                                             |
//+------------------------------------------------------------------+
string ClassifySymbol(const string sym)
{
   if((StringFind(sym, "XAU") >= 0 || StringFind(sym, "XAG") >= 0) &&
      StringFind(sym, "EUR") >= 0) return "metal_eur";
   if(StringFind(sym, "XAU") >= 0 || StringFind(sym, "XAG") >= 0) return "metal_usd";
   if(StringFind(sym, "JPY") >= 0) return "jpy_cross";
   if(StringFind(sym, "NOK") >= 0 || StringFind(sym, "SEK") >= 0) return "scandi";
   return "other";
}

string DefaultStrategyFor(const string cls)
{
   if(cls == "metal_usd" || cls == "metal_eur") return "continuation";
   if(cls == "jpy_cross") return "fade";
   if(cls == "scandi")    return "fade";
   return "continuation";
}

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(20);

   g_point  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   g_digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   g_symbol_class = ClassifySymbol(_Symbol);

   string strat = InpStrategy; StringToLower(strat);
   g_resolved_strategy = (strat == "auto") ? DefaultStrategyFor(g_symbol_class)
                       : (strat == "fade" ? "fade" : "continuation");

   // Indicator handles
   g_h_rsi_h1 = iRSI(_Symbol, PERIOD_H1, 14, PRICE_CLOSE);
   g_h_atr_h1 = iATR(_Symbol, PERIOD_H1, 14);
   g_h_ema_h1 = iMA (_Symbol, PERIOD_H1, 20, 0, MODE_EMA, PRICE_CLOSE);
   g_h_atr_d1 = iATR(_Symbol, PERIOD_D1, 14);
   if(g_h_rsi_h1 == INVALID_HANDLE || g_h_atr_h1 == INVALID_HANDLE ||
      g_h_ema_h1 == INVALID_HANDLE || g_h_atr_d1 == INVALID_HANDLE)
   {
      Print("[ERROR] Indicator handle creation failed");
      return INIT_FAILED;
   }

   // ONNX model. FILE_COMMON = read from Terminal/Common/Files/ which is
   // accessible from BOTH live and Strategy Tester (the local MQL5/Files
   // folder is sandboxed in tester mode).
   g_onnx_handle = OnnxCreate(InpOnnxFile, FILE_COMMON);
   if(g_onnx_handle == INVALID_HANDLE)
   {
      Print("[ERROR] OnnxCreate failed for '", InpOnnxFile, "': ", GetLastError());
      Print("        Place the .onnx file in Terminal/Common/Files/ of this terminal.");
      return INIT_FAILED;
   }

   // Set input shape: [1, 22]
   const long in_shape[] = {1, N_FEATURES};
   if(!OnnxSetInputShape(g_onnx_handle, 0, in_shape))
   {
      Print("[ERROR] OnnxSetInputShape failed: ", GetLastError());
      return INIT_FAILED;
   }
   // LightGBM zipmap=false outputs: [labels (int64 [N]), probas (float [N, 2])]
   const long out0_shape[] = {1};
   const long out1_shape[] = {1, 2};
   OnnxSetOutputShape(g_onnx_handle, 0, out0_shape);
   OnnxSetOutputShape(g_onnx_handle, 1, out1_shape);

   Print("======================================================================");
   Print("  WEEKEND GAP EA v2 ML - INIT");
   Print("======================================================================");
   Print("  Symbol:            ", _Symbol, "  (class: ", g_symbol_class, ", digits: ", g_digits, ")");
   Print("  Resolved strategy: ", g_resolved_strategy);
   Print("  ONNX file:         ", InpOnnxFile, "  (handle ", g_onnx_handle, ")");
   Print("  Proba threshold:   ", DoubleToString(InpProbaThreshold, 3));
   Print("  Pre-filter body:   >= ", DoubleToString(FIXED_MIN_BODY_PCT, 2), "%  [hardcoded]");
   Print("  Long-only filter:  ", FIXED_LONG_ONLY ? "ON" : "OFF", "  [hardcoded]");
   Print("  SL:                ", DoubleToString(FIXED_SL_PCT, 2), "%  [hardcoded]");
   Print("  Lot / Risk%:       ", DoubleToString(InpFixedLot, 2), " / ",
         DoubleToString(InpRiskPercent, 2), "%");
   Print("  Entry (UTC summer):Fri ", FIXED_ENTRY_HOUR_UTC, ":",
         (FIXED_ENTRY_MIN_UTC<10?"0":""), FIXED_ENTRY_MIN_UTC,
         " win=", FIXED_ENTRY_WIN_MIN, "min  (winter +1h auto)");
   Print("  Exit  (UTC summer):Sun ", FIXED_EXIT_HOUR_UTC, ":",
         (FIXED_EXIT_MIN_UTC<10?"0":""), FIXED_EXIT_MIN_UTC,
         " win=", FIXED_EXIT_WIN_MIN, "min  (winter +1h auto)");
   Print("  Magic:             ", InpMagic);
   Print("======================================================================");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_h_rsi_h1   != INVALID_HANDLE) IndicatorRelease(g_h_rsi_h1);
   if(g_h_atr_h1   != INVALID_HANDLE) IndicatorRelease(g_h_atr_h1);
   if(g_h_ema_h1   != INVALID_HANDLE) IndicatorRelease(g_h_ema_h1);
   if(g_h_atr_d1   != INVALID_HANDLE) IndicatorRelease(g_h_atr_d1);
   if(g_onnx_handle != INVALID_HANDLE) OnnxRelease(g_onnx_handle);
   if(InpPrintSummary && MQLInfoInteger(MQL_TESTER)) PrintSummaryReport();
}

//+------------------------------------------------------------------+
//| Time helpers                                                      |
//+------------------------------------------------------------------+
int _SeasonalShift(const MqlDateTime &dt_utc)
{
   if(!FIXED_MARKET_DST) return 0;
   return (dt_utc.mon >= 4 && dt_utc.mon <= 10) ? 0 : 1;
}

bool IsInEntryWindow(const MqlDateTime &dt_utc)
{
   if(dt_utc.day_of_week != FIXED_ENTRY_DOW) return false;
   int eff_hour = FIXED_ENTRY_HOUR_UTC + _SeasonalShift(dt_utc);
   int now_min = dt_utc.hour * 60 + dt_utc.min;
   int tgt_min = eff_hour * 60 + FIXED_ENTRY_MIN_UTC;
   return (now_min >= tgt_min && now_min <= tgt_min + FIXED_ENTRY_WIN_MIN);
}

bool IsInExitWindow(const MqlDateTime &dt_utc)
{
   int shift = _SeasonalShift(dt_utc);
   int eff_hour = FIXED_EXIT_HOUR_UTC + shift;
   int tgt_start = eff_hour * 60 + FIXED_EXIT_MIN_UTC;
   int tgt_end   = tgt_start + FIXED_EXIT_WIN_MIN;

   if(dt_utc.day_of_week == FIXED_EXIT_DOW && tgt_end < 24*60)
   {
      int now_min = dt_utc.hour * 60 + dt_utc.min;
      return (now_min >= tgt_start && now_min <= tgt_end);
   }
   if(tgt_end >= 24*60)
   {
      if(dt_utc.day_of_week == FIXED_EXIT_DOW)
      {
         int now_min = dt_utc.hour * 60 + dt_utc.min;
         return (now_min >= tgt_start);
      }
      if(dt_utc.day_of_week == (FIXED_EXIT_DOW + 1) % 7)
      {
         int now_min = dt_utc.hour * 60 + dt_utc.min;
         return (now_min <= tgt_end - 24*60);
      }
   }
   return false;
}

//+------------------------------------------------------------------+
//| Position helpers                                                  |
//+------------------------------------------------------------------+
bool HasOpenPosition()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Symbol() != _Symbol) continue;
      if(g_pos.Magic()  != InpMagic) continue;
      return true;
   }
   return false;
}

double NormalizeLot(double lot)
{
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double mn   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(step > 0) lot = MathRound(lot / step) * step;
   if(lot < mn) lot = mn;
   if(lot > mx) lot = mx;
   return NormalizeDouble(lot, 2);
}

double CalcLotSize(double sl_dist)
{
   if(InpRiskPercent <= 0.0 || sl_dist <= 0.0) return NormalizeLot(InpFixedLot);
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tv <= 0 || ts <= 0) return NormalizeLot(InpFixedLot);
   double risk = equity * InpRiskPercent / 100.0;
   double loss_per_lot = (sl_dist / ts) * tv;
   if(loss_per_lot <= 0) return NormalizeLot(InpFixedLot);
   return NormalizeLot(risk / loss_per_lot);
}

//+------------------------------------------------------------------+
//| FEATURES — must match Python forex/src/gap_features.py            |
//+------------------------------------------------------------------+
bool ComputeFeatures(matrix<float> &features, double &friday_body_pct, int &direction)
{
   // Reusable buffers
   double rsi[1], atr_h1[1], ema20[6], atr_d1_buf[ATR_PCTILE_WINDOW];

   // --- H1 last 24 bars: shift 0 (current incomplete) to shift 23 ---
   double cur_bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double h24_open = iOpen(_Symbol, PERIOD_H1, 23);
   if(h24_open <= 0 || cur_bid <= 0) return false;

   double h24_high = cur_bid, h24_low = cur_bid;
   for(int s = 0; s <= 23; s++)
   {
      double h = (s == 0 ? cur_bid : iHigh(_Symbol, PERIOD_H1, s));
      double l = (s == 0 ? cur_bid : iLow (_Symbol, PERIOD_H1, s));
      if(h > h24_high) h24_high = h;
      if(l < h24_low)  h24_low  = l;
   }
   double h24_return = (cur_bid - h24_open) / h24_open * 100.0;
   double h24_range  = (h24_high - h24_low) / h24_open * 100.0;

   // Friday body for direction (matches v1 logic, also used as feature 17 indirectly)
   double lookback_open = iOpen(_Symbol, PERIOD_H1, FIXED_LOOKBACK_H);
   if(lookback_open <= 0) return false;
   friday_body_pct = (cur_bid - lookback_open) / lookback_open * 100.0;
   direction = (friday_body_pct > 0 ? 1 : (friday_body_pct < 0 ? -1 : 0));

   // --- last H1 bar (shift 1, fully closed) ---
   double h1_open  = iOpen (_Symbol, PERIOD_H1, 1);
   double h1_close = iClose(_Symbol, PERIOD_H1, 1);
   double h1_high  = iHigh (_Symbol, PERIOD_H1, 1);
   double h1_low   = iLow  (_Symbol, PERIOD_H1, 1);
   if(h1_open <= 0) return false;
   double h1_last_return = (h1_close - h1_open) / h1_open * 100.0;
   double h1_last_range  = (h1_high  - h1_low ) / h1_open * 100.0;

   // RSI / ATR / EMA on H1 (use shift=1, last completed bar)
   if(CopyBuffer(g_h_rsi_h1, 0, 1, 1, rsi) <= 0) return false;
   if(CopyBuffer(g_h_atr_h1, 0, 1, 1, atr_h1) <= 0) return false;
   if(CopyBuffer(g_h_ema_h1, 0, 1, 6, ema20) <= 0) return false;  // need ema[0]=t-1, ema[5]=t-6 → slope
   double rsi_h1     = rsi[0];
   double atr_h1_pct = atr_h1[0] / cur_bid * 100.0;
   double ema_now    = ema20[5];   // most recent (shift=1)
   double ema_prev   = ema20[0];   // 5 bars before that (shift=6)
   double ema_slope_h1 = (ema_prev > 0) ? (ema_now - ema_prev) / ema_prev * 100.0 : 0.0;

   // --- D1 weekly context: last completed D1 bar (shift=1) ---
   double d1_open  = iOpen (_Symbol, PERIOD_D1, 1);
   double d1_close = iClose(_Symbol, PERIOD_D1, 1);
   double d1_high  = iHigh (_Symbol, PERIOD_D1, 1);
   double d1_low   = iLow  (_Symbol, PERIOD_D1, 1);
   if(d1_open <= 0) return false;
   double d1_body_pct  = (d1_close - d1_open) / d1_open * 100.0;
   double d1_range_pct = (d1_high  - d1_low ) / d1_open * 100.0;
   double body_ratio   = (d1_range_pct > 0) ? d1_body_pct / d1_range_pct : 0.0;

   double week_open = iOpen(_Symbol, PERIOD_D1, 6);
   double week_return = (week_open > 0) ? (d1_close - week_open) / week_open * 100.0 : 0.0;
   double week_range = d1_range_pct;

   // 5-day high/low across D1 bars 1..5 (last 5 trading days)
   double high_5d = d1_high, low_5d = d1_low;
   for(int s = 2; s <= 5; s++)
   {
      double h = iHigh(_Symbol, PERIOD_D1, s);
      double l = iLow (_Symbol, PERIOD_D1, s);
      if(h > high_5d) high_5d = h;
      if(l < low_5d)  low_5d  = l;
   }
   double dist_high5d_pct = (high_5d > 0) ? (d1_close - high_5d) / high_5d * 100.0 : 0.0;
   double dist_low5d_pct  = (low_5d  > 0) ? (d1_close - low_5d ) / low_5d  * 100.0 : 0.0;

   // ATR D1 percentile over rolling 60 bars
   if(CopyBuffer(g_h_atr_d1, 0, 1, ATR_PCTILE_WINDOW, atr_d1_buf) <= 0) return false;
   double cur_atr_d1 = atr_d1_buf[ATR_PCTILE_WINDOW - 1];  // most recent
   double cur_atr_pct = cur_atr_d1 / d1_close * 100.0;
   int below = 0;
   for(int i = 0; i < ATR_PCTILE_WINDOW; i++)
   {
      double a_pct = atr_d1_buf[i] / d1_close * 100.0;  // using d1_close as approx
      if(a_pct <= cur_atr_pct) below++;
   }
   double atr_pctile60 = (double)below / (double)ATR_PCTILE_WINDOW;

   // Temporal — derived from current UTC time
   datetime now = TimeCurrent() - (datetime)(InpBrokerGMTOffset * 3600);
   MqlDateTime dt; TimeToStruct(now, dt);
   int week_of_month = (int)((dt.day - 1) / 7 + 1);
   int month         = dt.mon;
   int quarter       = (int)((month - 1) / 3 + 1);
   int is_eom_friday = (week_of_month >= 4) ? 1 : 0;

   // Previous weekend gap: scan H1 history for the most recent gap >= 40h
   double prev_gap_pct = 0.0;
   for(int s = 1; s < 240; s++)  // search up to 10 days back
   {
      datetime t_now = iTime(_Symbol, PERIOD_H1, s);
      datetime t_prev = iTime(_Symbol, PERIOD_H1, s + 1);
      if(t_now == 0 || t_prev == 0) break;
      double gap_h = (double)(t_now - t_prev) / 3600.0;
      if(gap_h >= 40.0)
      {
         double open_after = iOpen(_Symbol, PERIOD_H1, s);
         double close_before = iClose(_Symbol, PERIOD_H1, s + 1);
         if(close_before > 0)
            prev_gap_pct = (open_after - close_before) / close_before * 100.0;
         break;
      }
   }
   double prev_gap_abs_pct = MathAbs(prev_gap_pct);

   // Symbol one-hot (alphabetical: XAGEUR, XAGUSD, XAUUSD)
   float sym_xageur = (_Symbol == "XAGEUR") ? 1.0f : 0.0f;
   float sym_xagusd = (_Symbol == "XAGUSD") ? 1.0f : 0.0f;
   float sym_xauusd = (_Symbol == "XAUUSD") ? 1.0f : 0.0f;

   // Fill matrix
   features.Init(1, N_FEATURES);
   features[0][0]  = (float)h24_return;
   features[0][1]  = (float)h24_range;
   features[0][2]  = (float)h1_last_return;
   features[0][3]  = (float)h1_last_range;
   features[0][4]  = (float)rsi_h1;
   features[0][5]  = (float)atr_h1_pct;
   features[0][6]  = (float)ema_slope_h1;
   features[0][7]  = (float)week_return;
   features[0][8]  = (float)week_range;
   features[0][9]  = (float)body_ratio;
   features[0][10] = (float)dist_high5d_pct;
   features[0][11] = (float)dist_low5d_pct;
   features[0][12] = (float)atr_pctile60;
   features[0][13] = (float)week_of_month;
   features[0][14] = (float)month;
   features[0][15] = (float)quarter;
   features[0][16] = (float)is_eom_friday;
   features[0][17] = (float)prev_gap_pct;
   features[0][18] = (float)prev_gap_abs_pct;
   features[0][19] = sym_xageur;
   features[0][20] = sym_xagusd;
   features[0][21] = sym_xauusd;
   return true;
}

//+------------------------------------------------------------------+
//| RUN ONNX                                                          |
//+------------------------------------------------------------------+
bool PredictProbaUp(const matrix<float> &features, double &proba_up)
{
   // LightGBM classifier (zipmap=False) outputs:
   //   [0] labels  : int64, shape [N]
   //   [1] probas  : float, shape [N, 2]
   long out_labels[];   ArrayResize(out_labels, 1);
   matrix<float> out_probas(1, 2);
   if(!OnnxRun(g_onnx_handle, ONNX_NO_CONVERSION, features, out_labels, out_probas))
   {
      Print("[ERROR] OnnxRun failed: ", GetLastError());
      return false;
   }
   proba_up = (double)out_probas[0][1];
   return true;
}

//+------------------------------------------------------------------+
//| OnTick                                                            |
//+------------------------------------------------------------------+
void OnTick()
{
   datetime now = TimeCurrent() - (datetime)(InpBrokerGMTOffset * 3600);
   MqlDateTime dt_utc; TimeToStruct(now, dt_utc);

   if(dt_utc.day_of_week == FIXED_ENTRY_DOW)
   {
      if(g_first_friday_seen == 0) g_first_friday_seen = now;
      g_last_friday_seen = now;
   }

   bool in_entry = IsInEntryWindow(dt_utc);
   bool in_exit  = IsInExitWindow(dt_utc);
   if(in_entry) g_ticks_in_entry_window++;
   if(in_exit)  g_ticks_in_exit_window++;

   if(!HasOpenPosition() && in_entry && now - g_last_entry_attempt >= 60)
   {
      g_last_entry_attempt = now;
      g_entry_attempts++;
      TryOpenWeekendTrade(now);
   }
   else if(HasOpenPosition() && in_exit && now - g_last_exit_attempt >= 60)
   {
      g_last_exit_attempt = now;
      g_exits_triggered++;
      TryCloseWeekendTrade(now);
   }
}

//+------------------------------------------------------------------+
//| TRY OPEN                                                          |
//+------------------------------------------------------------------+
void TryOpenWeekendTrade(datetime now_utc)
{
   long spread_pts = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread_pts > InpMaxSpreadPtsEntry) { g_entry_skipped_spread++; return; }

   matrix<float> features;
   double body_pct;
   int direction;
   if(!ComputeFeatures(features, body_pct, direction))
   {
      g_entry_skipped_feat++;
      if(InpLogEachWeekend) Print("[SKIP] features unavailable");
      return;
   }

   if(MathAbs(body_pct) < FIXED_MIN_BODY_PCT) { g_entry_skipped_body++; return; }

   // Strategy direction
   int trade_dir = (g_resolved_strategy == "fade") ? -direction : direction;
   if(trade_dir == 0) { g_entry_skipped_dir++; return; }
   if(FIXED_LONG_ONLY && trade_dir < 0) { g_entry_skipped_dir++; return; }

   // ML proba check
   double proba_up = 0.5;
   if(!PredictProbaUp(features, proba_up))
   {
      g_entry_skipped_feat++;
      return;
   }
   g_proba_count++;
   g_proba_sum += proba_up;
   if(proba_up < g_proba_min) g_proba_min = proba_up;
   if(proba_up > g_proba_max) g_proba_max = proba_up;

   // For long entries, we want proba_up >= threshold
   // For short entries, we want proba_up <= 1 - threshold (i.e., proba_down >= threshold)
   bool ml_pass = (trade_dir > 0) ? (proba_up >= InpProbaThreshold)
                                  : (proba_up <= 1.0 - InpProbaThreshold);
   if(!ml_pass)
   {
      g_entry_skipped_proba++;
      if(InpLogFeatures)
         Print("[SKIP-ML] ", TimeToString(now_utc, TIME_DATE|TIME_MINUTES),
               " body=", DoubleToString(body_pct, 3), "%",
               " dir=", (trade_dir > 0 ? "LONG" : "SHORT"),
               " proba_up=", DoubleToString(proba_up, 4),
               " thr=", DoubleToString(InpProbaThreshold, 3));
      return;
   }

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double entry_price = (trade_dir > 0 ? ask : bid);
   double sl_dist = entry_price * FIXED_SL_PCT / 100.0;
   double sl_price = (trade_dir > 0)
                     ? NormalizeDouble(entry_price - sl_dist, g_digits)
                     : NormalizeDouble(entry_price + sl_dist, g_digits);
   double tp_price = 0.0;
   if(InpTPPercent > 0)
      tp_price = (trade_dir > 0)
                 ? NormalizeDouble(entry_price + entry_price * InpTPPercent / 100.0, g_digits)
                 : NormalizeDouble(entry_price - entry_price * InpTPPercent / 100.0, g_digits);

   double lot = CalcLotSize(sl_dist);
   string comment = StringFormat("WGAPv2 %s body=%.2f%% p=%.3f",
                                 g_resolved_strategy, body_pct, proba_up);

   bool ok = (trade_dir > 0)
             ? g_trade.Buy (lot, _Symbol, ask, sl_price, tp_price, comment)
             : g_trade.Sell(lot, _Symbol, bid, sl_price, tp_price, comment);
   if(ok)
   {
      g_entry_opened++;
      if(InpLogEachWeekend)
         Print("[OPEN] ", TimeToString(now_utc, TIME_DATE|TIME_MINUTES),
               " ", (trade_dir > 0 ? "BUY" : "SELL"),
               " ", DoubleToString(lot, 2), " @ ", DoubleToString(entry_price, g_digits),
               " | body=", DoubleToString(body_pct, 3), "%",
               " | proba_up=", DoubleToString(proba_up, 4),
               " | SL=", DoubleToString(sl_price, g_digits));
      if(InpLogFeatures)
      {
         string feat_str = "  features=[";
         for(int i = 0; i < N_FEATURES; i++)
            feat_str += StringFormat("%.4f%s", features[0][i], (i < N_FEATURES-1 ? "," : ""));
         Print(feat_str, "]");
      }
   }
   else
      Print("[ERROR] Open failed: ", g_trade.ResultRetcode(), " - ", g_trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
//| TRY CLOSE                                                         |
//+------------------------------------------------------------------+
void TryCloseWeekendTrade(datetime now_utc)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Symbol() != _Symbol) continue;
      if(g_pos.Magic()  != InpMagic) continue;

      double cur_bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double cur_ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double exit_price = (g_pos.PositionType() == POSITION_TYPE_BUY ? cur_bid : cur_ask);
      double entry_price = g_pos.PriceOpen();
      double gap_pct = (g_pos.PositionType() == POSITION_TYPE_BUY)
                       ? (exit_price - entry_price) / entry_price * 100.0
                       : (entry_price - exit_price) / entry_price * 100.0;
      if(!g_trade.PositionClose(g_pos.Ticket()))
      {
         Print("[ERROR] Close failed: ", g_trade.ResultRetcode());
         continue;
      }
      if(InpLogEachWeekend)
         Print("[CLOSE] ", TimeToString(now_utc, TIME_DATE|TIME_MINUTES),
               " exit=", DoubleToString(exit_price, g_digits),
               " | gap_captured=", DoubleToString(gap_pct, 3), "%");
   }
}

//+------------------------------------------------------------------+
//| SUMMARY REPORT                                                    |
//+------------------------------------------------------------------+
void PrintSummaryReport()
{
   Print("======================================================================");
   Print("  WEEKEND GAP EA v2 ML - DIAGNOSTIC COUNTERS");
   Print("======================================================================");
   Print("  Ticks in entry window:  ", g_ticks_in_entry_window);
   Print("  Ticks in exit  window:  ", g_ticks_in_exit_window);
   Print("  First Friday tick UTC:  ",
         g_first_friday_seen > 0 ? TimeToString(g_first_friday_seen, TIME_DATE|TIME_MINUTES) : "NEVER");
   Print("  Last Friday tick UTC:   ",
         g_last_friday_seen > 0 ? TimeToString(g_last_friday_seen, TIME_DATE|TIME_MINUTES) : "NEVER");
   Print("  Entry attempts:         ", g_entry_attempts);
   Print("    skipped spread:       ", g_entry_skipped_spread);
   Print("    skipped body:         ", g_entry_skipped_body);
   Print("    skipped no-direction: ", g_entry_skipped_dir);
   Print("    skipped feat-err:     ", g_entry_skipped_feat);
   Print("    skipped ML proba:     ", g_entry_skipped_proba);
   Print("    OPENED:               ", g_entry_opened);
   Print("  Exits triggered:        ", g_exits_triggered);
   if(g_proba_count > 0)
      Print("  Proba seen: count=", g_proba_count,
            " min=", DoubleToString(g_proba_min, 4),
            " max=", DoubleToString(g_proba_max, 4),
            " avg=", DoubleToString(g_proba_sum / g_proba_count, 4));
   Print("");

   if(!HistorySelect(0, TimeCurrent())) return;
   int totalDeals = HistoryDealsTotal();
   if(totalDeals == 0)
   {
      Print("[SUMMARY] No deals recorded.");
      return;
   }

   int totalTrades = 0, wins = 0, losses = 0, longTr = 0, shortTr = 0, longWins = 0, shortWins = 0;
   double grossProfit = 0, grossLoss = 0, totalProfit = 0, longPnl = 0, shortPnl = 0;
   double maxWin = 0, maxLoss = 0;
   int maxWinStreak = 0, maxLossStreak = 0, curWinStreak = 0, curLossStreak = 0;
   double runningBal = 0, peakBal = 0, maxDD = 0;
   int tpCount = 0, slCount = 0, otherCount = 0;
   double tpPnl = 0, slPnl = 0, otherPnl = 0;
   int monthKeys[]; double monthPnl[]; int monthTrades[]; int monthWins[];
   int numMonths = 0;
   // Proba bucket performance: 0.55-0.6, 0.6-0.65, 0.65-0.7, 0.7+
   int probaBktN[4] = {0,0,0,0};
   int probaBktWins[4] = {0,0,0,0};
   double probaBktPnl[4] = {0,0,0,0};
   string probaBktName[4] = {"0.55-0.60", "0.60-0.65", "0.65-0.70", "0.70+"};

   for(int i = 0; i < totalDeals; i++)
   {
      ulong t = HistoryDealGetTicket(i);
      if(HistoryDealGetString(t, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(t, DEAL_MAGIC) != InpMagic) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(t, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;

      double net = HistoryDealGetDouble(t, DEAL_PROFIT) +
                   HistoryDealGetDouble(t, DEAL_SWAP) +
                   HistoryDealGetDouble(t, DEAL_COMMISSION);
      ENUM_DEAL_REASON reason = (ENUM_DEAL_REASON)HistoryDealGetInteger(t, DEAL_REASON);
      ENUM_DEAL_TYPE   dtype  = (ENUM_DEAL_TYPE)HistoryDealGetInteger(t, DEAL_TYPE);
      datetime exitTime = (datetime)HistoryDealGetInteger(t, DEAL_TIME);

      totalTrades++;
      totalProfit += net;
      runningBal += net;
      if(runningBal > peakBal) peakBal = runningBal;
      double dd = peakBal - runningBal;
      if(dd > maxDD) maxDD = dd;

      bool isWin = (net > 0);
      if(isWin) { wins++; grossProfit += net; if(net > maxWin) maxWin = net;
                  curWinStreak++; if(curWinStreak > maxWinStreak) maxWinStreak = curWinStreak; curLossStreak = 0; }
      else      { losses++; grossLoss += MathAbs(net); if(net < maxLoss) maxLoss = net;
                  curLossStreak++; if(curLossStreak > maxLossStreak) maxLossStreak = curLossStreak; curWinStreak = 0; }

      bool wasLong = (dtype == DEAL_TYPE_SELL);
      if(wasLong) { longTr++; longPnl += net; if(isWin) longWins++; }
      else        { shortTr++; shortPnl += net; if(isWin) shortWins++; }

      if(reason == DEAL_REASON_TP) { tpCount++; tpPnl += net; }
      else if(reason == DEAL_REASON_SL) { slCount++; slPnl += net; }
      else { otherCount++; otherPnl += net; }

      // Parse comment for proba (format: "WGAPv2 continuation body=X.XX% p=0.XXX")
      ulong posId = HistoryDealGetInteger(t, DEAL_POSITION_ID);
      double probaVal = 0.0;
      for(int j = 0; j < totalDeals; j++)
      {
         ulong t2 = HistoryDealGetTicket(j);
         if(HistoryDealGetInteger(t2, DEAL_POSITION_ID) == posId &&
            (ENUM_DEAL_ENTRY)HistoryDealGetInteger(t2, DEAL_ENTRY) == DEAL_ENTRY_IN)
         {
            string c = HistoryDealGetString(t2, DEAL_COMMENT);
            int p = StringFind(c, "p=");
            if(p >= 0)
            {
               string tail = StringSubstr(c, p + 2, 6);
               probaVal = StringToDouble(tail);
            }
            break;
         }
      }
      int bkt = -1;
      if(probaVal >= 0.55 && probaVal < 0.60) bkt = 0;
      else if(probaVal >= 0.60 && probaVal < 0.65) bkt = 1;
      else if(probaVal >= 0.65 && probaVal < 0.70) bkt = 2;
      else if(probaVal >= 0.70) bkt = 3;
      if(bkt >= 0)
      {
         probaBktN[bkt]++;
         probaBktPnl[bkt] += net;
         if(isWin) probaBktWins[bkt]++;
      }

      MqlDateTime dtm; TimeToStruct(exitTime, dtm);
      int mk = dtm.year * 100 + dtm.mon;
      int mi = -1;
      for(int m = 0; m < numMonths; m++) if(monthKeys[m] == mk) { mi = m; break; }
      if(mi == -1)
      {
         numMonths++;
         ArrayResize(monthKeys, numMonths); ArrayResize(monthPnl, numMonths);
         ArrayResize(monthTrades, numMonths); ArrayResize(monthWins, numMonths);
         mi = numMonths - 1;
         monthKeys[mi] = mk; monthPnl[mi] = 0; monthTrades[mi] = 0; monthWins[mi] = 0;
      }
      monthPnl[mi] += net; monthTrades[mi]++; if(isWin) monthWins[mi]++;
   }

   if(totalTrades == 0) { Print("[SUMMARY] No trades for this magic."); return; }

   double winRate = (double)wins / totalTrades * 100.0;
   double pf = (grossLoss > 0) ? grossProfit / grossLoss : 99;
   double avgWin = (wins > 0) ? grossProfit / wins : 0;
   double avgLoss = (losses > 0) ? grossLoss / losses : 0;
   double exp_ = (winRate/100.0 * avgWin) - ((100.0-winRate)/100.0 * avgLoss);
   double initBal = TesterStatistics(STAT_INITIAL_DEPOSIT);
   double retPct = (initBal > 0) ? totalProfit / initBal * 100.0 : 0;
   double rr = (avgLoss > 0) ? avgWin / avgLoss : 0;

   Print("======================================================================");
   Print("  WEEKEND GAP EA v2 ML - BACKTEST SUMMARY");
   Print("======================================================================");
   Print("");
   Print("--- PERFORMANCE ---");
   Print("  Initial Balance:    $", DoubleToString(initBal, 2));
   Print("  Final Balance:      $", DoubleToString(initBal + totalProfit, 2));
   Print("  Net Profit:         $", DoubleToString(totalProfit, 2));
   Print("  Return:             ", DoubleToString(retPct, 2), "%");
   Print("  Max Drawdown:       $", DoubleToString(maxDD, 2));
   Print("  Profit Factor:      ", DoubleToString(pf, 2));
   Print("  Expectancy/trade:   $", DoubleToString(exp_, 2));
   Print("");
   Print("--- TRADES ---");
   Print("  Total:              ", totalTrades);
   Print("  Wins / Losses:      ", wins, " (", DoubleToString(winRate,1), "%) / ", losses);
   Print("  Avg Winner / Loser: $", DoubleToString(avgWin,2), " / $", DoubleToString(avgLoss,2));
   Print("  Best / Worst trade: $", DoubleToString(maxWin,2), " / $", DoubleToString(maxLoss,2));
   Print("  Max Win/Loss Streak:", maxWinStreak, " / ", maxLossStreak);
   Print("  Realized R:R:       1:", DoubleToString(rr, 2));
   Print("");
   Print("--- EXIT REASONS ---");
   Print("  TP / SL / Other:    ", tpCount, " ($", DoubleToString(tpPnl,2), ") / ",
         slCount, " ($", DoubleToString(slPnl,2), ") / ",
         otherCount, " ($", DoubleToString(otherPnl,2), ")");
   Print("");
   Print("--- DIRECTION ---");
   if(longTr  > 0) Print("  LONG : n=", longTr,  " WR=", DoubleToString((double)longWins/longTr*100,1), "% PnL=$", DoubleToString(longPnl,2));
   if(shortTr > 0) Print("  SHORT: n=", shortTr, " WR=", DoubleToString((double)shortWins/shortTr*100,1), "% PnL=$", DoubleToString(shortPnl,2));
   Print("");
   Print("--- PROBA BUCKETS (model confidence) ---");
   for(int b = 0; b < 4; b++)
   {
      if(probaBktN[b] == 0) { Print("  ", probaBktName[b], ": n=0"); continue; }
      Print("  ", probaBktName[b], ": n=", probaBktN[b],
            " WR=", DoubleToString((double)probaBktWins[b]/probaBktN[b]*100,1), "%",
            " PnL=$", DoubleToString(probaBktPnl[b],2),
            " Avg=$", DoubleToString(probaBktPnl[b]/probaBktN[b],2));
   }
   Print("");

   for(int a = 0; a < numMonths-1; a++)
      for(int b = a+1; b < numMonths; b++)
         if(monthKeys[b] < monthKeys[a])
         { int tk=monthKeys[a]; monthKeys[a]=monthKeys[b]; monthKeys[b]=tk;
           double tp=monthPnl[a]; monthPnl[a]=monthPnl[b]; monthPnl[b]=tp;
           int tt=monthTrades[a]; monthTrades[a]=monthTrades[b]; monthTrades[b]=tt;
           int tw=monthWins[a]; monthWins[a]=monthWins[b]; monthWins[b]=tw; }

   Print("--- MONTHLY ---");
   int profMonths = 0; double cum = initBal;
   for(int m = 0; m < numMonths; m++)
   {
      int yr = monthKeys[m]/100, mn = monthKeys[m]%100;
      double mwr = (monthTrades[m] > 0) ? (double)monthWins[m]/monthTrades[m]*100.0 : 0;
      cum += monthPnl[m];
      string mk = (monthPnl[m] > 0 ? "+" : (monthPnl[m] < 0 ? "-" : "="));
      Print("  ", yr, "-", (mn<10?"0":""), mn,
            " | PnL=$", DoubleToString(monthPnl[m], 2),
            " | n=", monthTrades[m],
            " | WR=", DoubleToString(mwr, 0), "%",
            " | bal=$", DoubleToString(cum, 2), "  ", mk);
      if(monthPnl[m] > 0) profMonths++;
   }
   Print("  Profitable months:  ", profMonths, "/", numMonths,
         " (", DoubleToString((double)profMonths/MathMax(1,numMonths)*100.0,0), "%)");
   Print("");
   Print("--- SETTINGS ---");
   Print("  ONNX file:          ", InpOnnxFile);
   Print("  Proba threshold:    ", DoubleToString(InpProbaThreshold, 3));
   Print("  Lot:                ", DoubleToString(InpFixedLot, 2));
   Print("  SL %:               ", DoubleToString(FIXED_SL_PCT, 2), " [hardcoded]");
   Print("  Min body %:         ", DoubleToString(FIXED_MIN_BODY_PCT, 2), " [hardcoded]");
   Print("  Long-only:          ", FIXED_LONG_ONLY ? "ON" : "OFF", " [hardcoded]");
   Print("  Magic:              ", InpMagic);
   Print("");
   Print("======================================================================");
   Print("  Copy everything above and paste into the chat for analysis");
   Print("======================================================================");
}
