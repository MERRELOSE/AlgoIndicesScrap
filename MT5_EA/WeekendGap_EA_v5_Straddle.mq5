//+------------------------------------------------------------------+
//|                   WeekendGap_EA_v5_Straddle.mq5                   |
//|  Simultaneous BUY + SELL at Friday close, SL 0.10% each.         |
//|  On Sunday open: one SL fires on the loser side, close the        |
//|  winner immediately. No direction prediction needed.              |
//+------------------------------------------------------------------+
//  CONCEPT:
//  Instead of predicting gap direction, we straddle it:
//    - Friday 19:15 UTC: open BUY (SL 0.10% below ask) + SELL (SL 0.10% above bid)
//    - Sunday 22:15 UTC: close all remaining open positions
//
//  P&L mechanics per trade:
//    If gap > SL (0.10%):
//      Winner side: +gap% - spread
//      Loser  side: SL fills at gap-open price (slippage) = -gap% - spread
//      Net straddle: -2×spread (symmetric break-even MINUS cost)
//
//    EXCEPTION (profitable): If broker guarantees SL fill at the SL level
//    (no gap slippage), then:
//      Winner: +gap% - spread
//      Loser : -0.10% - spread
//      Net   : +(gap% - 0.10%) - 2×spread  → profitable when gap >> spread
//
//  On Deriv, metals SL may slip through a gap. Test empirically.
//  Pre-filter: Friday body >= MIN_BODY_PCT (1.0%) = quality gate for a real move.
//
//  v5 does NOT require the ONNX model (set InpUseML=false).
//  If InpUseML=true and ONNX loads, it is used as an extra filter:
//  trade only when model is confident (proba_up >= thr OR proba_up <= 1-thr).
//+------------------------------------------------------------------+
#property copyright "AlgoIndicesScrap"
#property version   "5.00"
#property description "Weekend gap straddle EA v5 - both BUY+SELL, direction-agnostic."
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//+------------------------------------------------------------------+
//| INPUTS                                                            |
//+------------------------------------------------------------------+
input group "=== Risk / Sizing ==="
input double InpFixedLot        = 0.01;     // lot per side (BUY and SELL each get this)
input double InpRiskPercent     = 0.0;      // >0 = risk-based lot sizing
input int    InpMagic           = 790050;   // v5 magic (must differ from v3/v4)

input group "=== Strategy ==="
input double InpMinBodyPct      = 1.00;     // Friday body filter (pre-filter quality gate)
input int    InpLookbackH       = 20;       // H1 bars back for Friday body

input group "=== ML model (optional) ==="
input bool   InpUseML           = false;    // false = pure straddle, true = model confidence gate
input string InpOnnxFile        = "weekend_gap.onnx";  // Terminal/Common/Files/
input double InpProbaThreshold  = 0.60;     // gate: proba_up >= thr OR <= 1-thr
input bool   InpLogFeatures     = false;

input group "=== Timing (UTC) ==="
input bool   InpMarketDST       = true;     // true = +1h shift Nov-Mar (NYSE DST)

input group "=== Broker ==="
input int    InpBrokerGMTOffset = 0;        // Deriv server = UTC (offset 0)

input group "=== Safety ==="
input int    InpMaxSpreadPtsEntry = 50;
input int    InpMaxSpreadPtsExit  = 500;

input group "=== Logging ==="
input bool   InpLogEachWeekend  = true;
input bool   InpPrintSummary    = true;

//+------------------------------------------------------------------+
//| HARDCODED TIMING                                                  |
//+------------------------------------------------------------------+
#define FIXED_ENTRY_DOW       5      // Friday
#define FIXED_ENTRY_HOUR_UTC  19     // summer UTC; winter = +1h
#define FIXED_ENTRY_MIN_UTC   15
#define FIXED_ENTRY_WIN_MIN   45     // 45-min window: 19:15-20:00 summer
#define FIXED_EXIT_DOW        0      // Sunday
#define FIXED_EXIT_HOUR_UTC   22     // summer UTC; winter = +1h
#define FIXED_EXIT_MIN_UTC    15
#define FIXED_EXIT_WIN_MIN    60     // 60-min window: 22:15-23:15 summer

#define FIXED_SL_PCT          0.10   // tight SL on each side
#define N_FEATURES            22
#define ATR_PCTILE_WINDOW     60

//+------------------------------------------------------------------+
//| GLOBALS                                                           |
//+------------------------------------------------------------------+
CTrade        g_trade;
CPositionInfo g_pos;

double  g_point  = 0.0;
int     g_digits = 0;
long    g_onnx_handle = INVALID_HANDLE;

int g_h_rsi_h1   = INVALID_HANDLE;
int g_h_atr_h1   = INVALID_HANDLE;
int g_h_ema_h1   = INVALID_HANDLE;
int g_h_atr_d1   = INVALID_HANDLE;

datetime g_last_entry_attempt = 0;
datetime g_last_exit_attempt  = 0;

// Counters
int g_ticks_entry_win   = 0;
int g_ticks_exit_win    = 0;
int g_entry_attempts    = 0;
int g_entry_opened      = 0;   // pairs opened (each = 1 BUY + 1 SELL)
int g_skipped_spread    = 0;
int g_skipped_body      = 0;
int g_skipped_ml        = 0;
int g_skipped_feat      = 0;
int g_exits_triggered   = 0;
datetime g_first_friday = 0;
datetime g_last_friday  = 0;

//+------------------------------------------------------------------+
//| Time helpers                                                      |
//+------------------------------------------------------------------+
int SeasonalShift(const MqlDateTime &dt)
{
   if(!InpMarketDST) return 0;
   return (dt.mon >= 4 && dt.mon <= 10) ? 0 : 1;
}

bool IsInEntryWindow(const MqlDateTime &dt)
{
   if(dt.day_of_week != FIXED_ENTRY_DOW) return false;
   int eff_hour = FIXED_ENTRY_HOUR_UTC + SeasonalShift(dt);
   int now_min  = dt.hour * 60 + dt.min;
   int tgt_min  = eff_hour * 60 + FIXED_ENTRY_MIN_UTC;
   return (now_min >= tgt_min && now_min <= tgt_min + FIXED_ENTRY_WIN_MIN);
}

bool IsInExitWindow(const MqlDateTime &dt)
{
   int shift     = SeasonalShift(dt);
   int eff_hour  = FIXED_EXIT_HOUR_UTC + shift;
   int tgt_start = eff_hour * 60 + FIXED_EXIT_MIN_UTC;
   int tgt_end   = tgt_start + FIXED_EXIT_WIN_MIN;

   if(dt.day_of_week == FIXED_EXIT_DOW && tgt_end < 24 * 60)
   {
      int now_min = dt.hour * 60 + dt.min;
      return (now_min >= tgt_start && now_min <= tgt_end);
   }
   if(tgt_end >= 24 * 60)
   {
      if(dt.day_of_week == FIXED_EXIT_DOW)
      {
         int now_min = dt.hour * 60 + dt.min;
         return (now_min >= tgt_start);
      }
      if(dt.day_of_week == (FIXED_EXIT_DOW + 1) % 7)
      {
         int now_min = dt.hour * 60 + dt.min;
         return (now_min <= tgt_end - 24 * 60);
      }
   }
   return false;
}

//+------------------------------------------------------------------+
//| Position helpers                                                  |
//+------------------------------------------------------------------+
int CountOurPositions()
{
   int cnt = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Symbol() != _Symbol) continue;
      if(g_pos.Magic()  != InpMagic) continue;
      cnt++;
   }
   return cnt;
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
   double tv     = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double ts     = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tv <= 0 || ts <= 0) return NormalizeLot(InpFixedLot);
   double risk        = equity * InpRiskPercent / 100.0;
   double loss_per_lot = (sl_dist / ts) * tv;
   if(loss_per_lot <= 0) return NormalizeLot(InpFixedLot);
   return NormalizeLot(risk / loss_per_lot);
}

//+------------------------------------------------------------------+
//| SL calculation with broker minimum check (from v3.1)             |
//+------------------------------------------------------------------+
double CalcSLBuy(double ask, double bid)
{
   double sl_dist  = ask * FIXED_SL_PCT / 100.0;
   double sl_price = NormalizeDouble(ask - sl_dist, g_digits);
   long   min_pts  = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double min_dist = (min_pts + 50) * g_point;
   double max_sl   = bid - min_dist;
   if(sl_price > max_sl) sl_price = NormalizeDouble(max_sl, g_digits);
   return sl_price;
}

double CalcSLSell(double ask, double bid)
{
   double sl_dist  = bid * FIXED_SL_PCT / 100.0;
   double sl_price = NormalizeDouble(bid + sl_dist, g_digits);
   long   min_pts  = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double min_dist = (min_pts + 50) * g_point;
   double min_sl   = ask + min_dist;
   if(sl_price < min_sl) sl_price = NormalizeDouble(min_sl, g_digits);
   return sl_price;
}

//+------------------------------------------------------------------+
//| ML features (identical to v3.1 — used only if InpUseML=true)     |
//+------------------------------------------------------------------+
bool ComputeFeatures(matrix<float> &features, double &body_pct)
{
   double rsi[1], atr_h1[1], ema20[6], atr_d1_buf[ATR_PCTILE_WINDOW];
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

   double lookback_open = iOpen(_Symbol, PERIOD_H1, InpLookbackH);
   if(lookback_open <= 0) return false;
   body_pct = (cur_bid - lookback_open) / lookback_open * 100.0;

   double h1_open  = iOpen (_Symbol, PERIOD_H1, 1);
   double h1_close = iClose(_Symbol, PERIOD_H1, 1);
   double h1_high  = iHigh (_Symbol, PERIOD_H1, 1);
   double h1_low   = iLow  (_Symbol, PERIOD_H1, 1);
   if(h1_open <= 0) return false;
   double h1_last_return = (h1_close - h1_open) / h1_open * 100.0;
   double h1_last_range  = (h1_high  - h1_low ) / h1_open * 100.0;

   if(CopyBuffer(g_h_rsi_h1, 0, 1, 1, rsi)    <= 0) return false;
   if(CopyBuffer(g_h_atr_h1, 0, 1, 1, atr_h1) <= 0) return false;
   if(CopyBuffer(g_h_ema_h1, 0, 1, 6, ema20)  <= 0) return false;
   double rsi_h1      = rsi[0];
   double atr_h1_pct  = atr_h1[0] / cur_bid * 100.0;
   double ema_now     = ema20[5];
   double ema_prev    = ema20[0];
   double ema_slope   = (ema_prev > 0) ? (ema_now - ema_prev) / ema_prev * 100.0 : 0.0;

   double d1_open  = iOpen (_Symbol, PERIOD_D1, 1);
   double d1_close = iClose(_Symbol, PERIOD_D1, 1);
   double d1_high  = iHigh (_Symbol, PERIOD_D1, 1);
   double d1_low   = iLow  (_Symbol, PERIOD_D1, 1);
   if(d1_open <= 0) return false;
   double d1_body_pct  = (d1_close - d1_open) / d1_open * 100.0;
   double d1_range_pct = (d1_high  - d1_low ) / d1_open * 100.0;
   double body_ratio   = (d1_range_pct > 0) ? d1_body_pct / d1_range_pct : 0.0;

   double week_open   = iOpen(_Symbol, PERIOD_D1, 6);
   double week_return = (week_open > 0) ? (d1_close - week_open) / week_open * 100.0 : 0.0;

   double high_5d = d1_high, low_5d = d1_low;
   for(int s = 2; s <= 5; s++)
   {
      double h = iHigh(_Symbol, PERIOD_D1, s);
      double l = iLow (_Symbol, PERIOD_D1, s);
      if(h > high_5d) high_5d = h;
      if(l < low_5d)  low_5d  = l;
   }
   double dist_high5d = (high_5d > 0) ? (d1_close - high_5d) / high_5d * 100.0 : 0.0;
   double dist_low5d  = (low_5d  > 0) ? (d1_close - low_5d ) / low_5d  * 100.0 : 0.0;

   if(CopyBuffer(g_h_atr_d1, 0, 1, ATR_PCTILE_WINDOW, atr_d1_buf) <= 0) return false;
   double cur_atr_d1  = atr_d1_buf[ATR_PCTILE_WINDOW - 1];
   double cur_atr_pct = cur_atr_d1 / d1_close * 100.0;
   int below = 0;
   for(int i = 0; i < ATR_PCTILE_WINDOW; i++)
   {
      double a_pct = atr_d1_buf[i] / d1_close * 100.0;
      if(a_pct <= cur_atr_pct) below++;
   }
   double atr_pctile = (double)below / (double)ATR_PCTILE_WINDOW;

   datetime now = TimeCurrent() - (datetime)(InpBrokerGMTOffset * 3600);
   MqlDateTime dt; TimeToStruct(now, dt);
   int wom       = (int)((dt.day - 1) / 7 + 1);
   int month     = dt.mon;
   int quarter   = (int)((month - 1) / 3 + 1);
   int is_eom    = (wom >= 4) ? 1 : 0;

   double prev_gap_pct = 0.0;
   for(int s = 1; s < 240; s++)
   {
      datetime t_now  = iTime(_Symbol, PERIOD_H1, s);
      datetime t_prev = iTime(_Symbol, PERIOD_H1, s + 1);
      if(t_now == 0 || t_prev == 0) break;
      double gap_h = (double)(t_now - t_prev) / 3600.0;
      if(gap_h >= 40.0)
      {
         double open_after   = iOpen (_Symbol, PERIOD_H1, s);
         double close_before = iClose(_Symbol, PERIOD_H1, s + 1);
         if(close_before > 0) prev_gap_pct = (open_after - close_before) / close_before * 100.0;
         break;
      }
   }
   double prev_gap_abs = MathAbs(prev_gap_pct);

   float sym_xageur = (_Symbol == "XAGEUR") ? 1.0f : 0.0f;
   float sym_xagusd = (_Symbol == "XAGUSD") ? 1.0f : 0.0f;
   float sym_xauusd = (_Symbol == "XAUUSD") ? 1.0f : 0.0f;

   features.Init(1, N_FEATURES);
   features[0][0]  = (float)h24_return;
   features[0][1]  = (float)h24_range;
   features[0][2]  = (float)h1_last_return;
   features[0][3]  = (float)h1_last_range;
   features[0][4]  = (float)rsi_h1;
   features[0][5]  = (float)atr_h1_pct;
   features[0][6]  = (float)ema_slope;
   features[0][7]  = (float)week_return;
   features[0][8]  = (float)d1_range_pct;
   features[0][9]  = (float)body_ratio;
   features[0][10] = (float)dist_high5d;
   features[0][11] = (float)dist_low5d;
   features[0][12] = (float)atr_pctile;
   features[0][13] = (float)wom;
   features[0][14] = (float)month;
   features[0][15] = (float)quarter;
   features[0][16] = (float)is_eom;
   features[0][17] = (float)prev_gap_pct;
   features[0][18] = (float)prev_gap_abs;
   features[0][19] = sym_xageur;
   features[0][20] = sym_xagusd;
   features[0][21] = sym_xauusd;
   return true;
}

bool PredictProbaUp(const matrix<float> &features, double &proba_up)
{
   long out_labels[];    ArrayResize(out_labels, 1);
   matrix<float> out_probas(1, 2);
   if(!OnnxRun(g_onnx_handle, ONNX_NO_CONVERSION, features, out_labels, out_probas))
   {
      Print("[ERROR] OnnxRun: ", GetLastError());
      return false;
   }
   proba_up = (double)out_probas[0][1];
   return true;
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

   g_h_rsi_h1 = iRSI(_Symbol, PERIOD_H1, 14, PRICE_CLOSE);
   g_h_atr_h1 = iATR(_Symbol, PERIOD_H1, 14);
   g_h_ema_h1 = iMA (_Symbol, PERIOD_H1, 20, 0, MODE_EMA, PRICE_CLOSE);
   g_h_atr_d1 = iATR(_Symbol, PERIOD_D1, 14);
   if(g_h_rsi_h1 == INVALID_HANDLE || g_h_atr_h1 == INVALID_HANDLE ||
      g_h_ema_h1 == INVALID_HANDLE || g_h_atr_d1 == INVALID_HANDLE)
   {
      Print("[ERROR] Indicator handle init failed");
      return INIT_FAILED;
   }

   if(InpUseML)
   {
      g_onnx_handle = OnnxCreate(InpOnnxFile, FILE_COMMON);
      if(g_onnx_handle == INVALID_HANDLE)
      {
         Print("[ERROR] OnnxCreate failed: ", GetLastError(),
               "  → place ", InpOnnxFile, " in Terminal/Common/Files/");
         return INIT_FAILED;
      }
      const long in_shape[]   = {1, N_FEATURES};
      const long out0_shape[] = {1};
      const long out1_shape[] = {1, 2};
      if(!OnnxSetInputShape(g_onnx_handle, 0, in_shape))
         { Print("[ERROR] OnnxSetInputShape: ", GetLastError()); return INIT_FAILED; }
      OnnxSetOutputShape(g_onnx_handle, 0, out0_shape);
      OnnxSetOutputShape(g_onnx_handle, 1, out1_shape);
   }

   Print("======================================================================");
   Print("  WEEKEND GAP EA v5 STRADDLE - INIT");
   Print("======================================================================");
   Print("  Symbol:      ", _Symbol, "  (digits ", g_digits, ")");
   Print("  Mode:        BUY + SELL straddle (direction-agnostic)");
   Print("  ML gate:     ", InpUseML ? "ON (proba_up >= " + DoubleToString(InpProbaThreshold,3) +
                                        " OR <= " + DoubleToString(1-InpProbaThreshold,3) + ")"
                                      : "OFF");
   Print("  Min body:    >= ", DoubleToString(InpMinBodyPct, 2), "%");
   Print("  SL each side:", DoubleToString(FIXED_SL_PCT, 2), "% (bid-based min check)");
   Print("  Lot/side:    ", DoubleToString(InpFixedLot, 2),
         InpRiskPercent > 0 ? "  (risk-based: " + DoubleToString(InpRiskPercent,2) + "%)" : "  (fixed)");
   Print("  Entry:  Fri ", FIXED_ENTRY_HOUR_UTC, ":", (FIXED_ENTRY_MIN_UTC<10?"0":""), FIXED_ENTRY_MIN_UTC,
         " UTC summer  (+1h Nov-Mar)");
   Print("  Exit:   Sun ", FIXED_EXIT_HOUR_UTC,  ":", (FIXED_EXIT_MIN_UTC<10?"0":""),  FIXED_EXIT_MIN_UTC,
         " UTC summer  (+1h Nov-Mar)");
   Print("  Magic:  ", InpMagic);
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
//| OnTick                                                            |
//+------------------------------------------------------------------+
void OnTick()
{
   datetime now = TimeCurrent() - (datetime)(InpBrokerGMTOffset * 3600);
   MqlDateTime dt; TimeToStruct(now, dt);

   if(dt.day_of_week == FIXED_ENTRY_DOW)
   {
      if(g_first_friday == 0) g_first_friday = now;
      g_last_friday = now;
   }

   bool in_entry = IsInEntryWindow(dt);
   bool in_exit  = IsInExitWindow(dt);
   if(in_entry) g_ticks_entry_win++;
   if(in_exit)  g_ticks_exit_win++;

   int pos_count = CountOurPositions();

   // Entry: only when 0 positions open
   if(pos_count == 0 && in_entry && now - g_last_entry_attempt >= 60)
   {
      g_last_entry_attempt = now;
      g_entry_attempts++;
      TryOpenStraddle(now);
   }
   // Exit: close all when 1 or more positions still open at exit window
   else if(pos_count > 0 && in_exit && now - g_last_exit_attempt >= 60)
   {
      g_last_exit_attempt = now;
      g_exits_triggered++;
      TryCloseAll(now);
   }
}

//+------------------------------------------------------------------+
//| TRY OPEN: places BUY + SELL simultaneously                        |
//+------------------------------------------------------------------+
void TryOpenStraddle(datetime now_utc)
{
   long spread_pts = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread_pts > InpMaxSpreadPtsEntry) { g_skipped_spread++; return; }

   double body_pct = 0.0;

   // ML gate path: compute features + proba check
   if(InpUseML)
   {
      matrix<float> features;
      if(!ComputeFeatures(features, body_pct)) { g_skipped_feat++; return; }
      if(MathAbs(body_pct) < InpMinBodyPct)    { g_skipped_body++; return; }

      double proba_up = 0.5;
      if(!PredictProbaUp(features, proba_up))  { g_skipped_feat++; return; }
      // Model must be confident in some direction (not neutral)
      bool ml_ok = (proba_up >= InpProbaThreshold || proba_up <= 1.0 - InpProbaThreshold);
      if(!ml_ok) { g_skipped_ml++; return; }
      if(InpLogFeatures)
         Print("[ML] proba_up=", DoubleToString(proba_up,4), " → straddle OK");
   }
   else
   {
      // No ML: compute body manually using lookback
      double cur_bid      = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double lookback_open = iOpen(_Symbol, PERIOD_H1, InpLookbackH);
      if(lookback_open <= 0 || cur_bid <= 0) { g_skipped_feat++; return; }
      body_pct = (cur_bid - lookback_open) / lookback_open * 100.0;
      if(MathAbs(body_pct) < InpMinBodyPct) { g_skipped_body++; return; }
   }

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   // --- BUY leg ---
   double buy_sl   = CalcSLBuy(ask, bid);
   double buy_dist = ask - buy_sl;
   double buy_lot  = CalcLotSize(buy_dist);
   string buy_cmt  = StringFormat("WGAPv5_BUY body=%.2f%%", body_pct);

   bool buy_ok = g_trade.Buy(buy_lot, _Symbol, ask, buy_sl, 0.0, buy_cmt);
   if(!buy_ok)
   {
      Print("[ERROR] BUY leg failed: ", g_trade.ResultRetcode(), " - ", g_trade.ResultRetcodeDescription());
      return;
   }

   // --- SELL leg (opened right after BUY) ---
   double sell_sl   = CalcSLSell(ask, bid);
   double sell_dist = sell_sl - bid;
   double sell_lot  = CalcLotSize(sell_dist);
   string sell_cmt  = StringFormat("WGAPv5_SELL body=%.2f%%", body_pct);

   bool sell_ok = g_trade.Sell(sell_lot, _Symbol, bid, sell_sl, 0.0, sell_cmt);
   if(!sell_ok)
   {
      Print("[ERROR] SELL leg failed: ", g_trade.ResultRetcode(), " - ", g_trade.ResultRetcodeDescription());
      // BUY already open — close it to avoid unhedged exposure
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         if(!g_pos.SelectByIndex(i)) continue;
         if(g_pos.Symbol() != _Symbol) continue;
         if(g_pos.Magic()  != InpMagic) continue;
         if(g_pos.PositionType() == POSITION_TYPE_BUY)
         {
            g_trade.PositionClose(g_pos.Ticket());
            Print("[ABORT] Rolled back BUY leg after SELL failure");
         }
      }
      return;
   }

   g_entry_opened++;
   if(InpLogEachWeekend)
      Print("[OPEN STRADDLE] ", TimeToString(now_utc, TIME_DATE|TIME_MINUTES),
            " BUY ", DoubleToString(buy_lot,2), " @ ", DoubleToString(ask, g_digits),
            " SL=", DoubleToString(buy_sl, g_digits),
            " | SELL ", DoubleToString(sell_lot,2), " @ ", DoubleToString(bid, g_digits),
            " SL=", DoubleToString(sell_sl, g_digits),
            " | body=", DoubleToString(body_pct, 3), "%",
            " | spread=", spread_pts, "pts");
}

//+------------------------------------------------------------------+
//| TRY CLOSE: close all remaining positions (winner + any SL misses)  |
//+------------------------------------------------------------------+
void TryCloseAll(datetime now_utc)
{
   long spread_pts = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread_pts > InpMaxSpreadPtsExit)
   {
      if(InpLogEachWeekend)
         Print("[EXIT DELAY] spread=", spread_pts, "pts > max ", InpMaxSpreadPtsExit);
      return;
   }

   int closed = 0;
   double total_pnl = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Symbol() != _Symbol) continue;
      if(g_pos.Magic()  != InpMagic) continue;

      double entry      = g_pos.PriceOpen();
      double cur_bid    = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double cur_ask    = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double exit_price = (g_pos.PositionType() == POSITION_TYPE_BUY) ? cur_bid : cur_ask;
      double gap_pct    = (g_pos.PositionType() == POSITION_TYPE_BUY)
                          ? (exit_price - entry) / entry * 100.0
                          : (entry - exit_price) / entry * 100.0;
      double pnl        = g_pos.Profit();
      total_pnl        += pnl;

      if(!g_trade.PositionClose(g_pos.Ticket()))
      {
         Print("[ERROR] Close failed ticket=", g_pos.Ticket(), " code=", g_trade.ResultRetcode());
         continue;
      }
      closed++;
      if(InpLogEachWeekend)
         Print("[CLOSE] ", TimeToString(now_utc, TIME_DATE|TIME_MINUTES),
               " ", (g_pos.PositionType()==POSITION_TYPE_BUY ? "BUY" : "SELL"),
               " exit=", DoubleToString(exit_price, g_digits),
               " gap=", DoubleToString(gap_pct, 3), "%",
               " pnl=$", DoubleToString(pnl, 2));
   }
   if(closed > 0 && InpLogEachWeekend)
      Print("[STRADDLE NET] closed=", closed, " total_pnl=$", DoubleToString(total_pnl, 2));
}

//+------------------------------------------------------------------+
//| SUMMARY REPORT                                                    |
//+------------------------------------------------------------------+
void PrintSummaryReport()
{
   Print("======================================================================");
   Print("  WEEKEND GAP EA v5 STRADDLE - DIAGNOSTIC");
   Print("======================================================================");
   Print("  Ticks in entry window: ", g_ticks_entry_win);
   Print("  Ticks in exit  window: ", g_ticks_exit_win);
   Print("  First Friday UTC:      ",
         g_first_friday > 0 ? TimeToString(g_first_friday, TIME_DATE|TIME_MINUTES) : "NEVER");
   Print("  Last Friday UTC:       ",
         g_last_friday > 0 ? TimeToString(g_last_friday, TIME_DATE|TIME_MINUTES) : "NEVER");
   Print("  Entry attempts:        ", g_entry_attempts);
   Print("    skipped spread:      ", g_skipped_spread);
   Print("    skipped body:        ", g_skipped_body);
   Print("    skipped ML:          ", g_skipped_ml);
   Print("    skipped feat-err:    ", g_skipped_feat);
   Print("    OPENED (pairs):      ", g_entry_opened);
   Print("  Exit windows fired:    ", g_exits_triggered);
   Print("  ML gate:               ", InpUseML ? "ON" : "OFF");

   if(!HistorySelect(0, TimeCurrent())) return;
   int total_deals = HistoryDealsTotal();
   if(total_deals == 0) { Print("[SUMMARY] No deals."); return; }

   int n_buy_wins=0, n_buy_losses=0, n_sell_wins=0, n_sell_losses=0;
   double buy_pnl=0, sell_pnl=0, total_pnl=0;
   double gross_profit=0, gross_loss=0;
   int total_exits=0;
   double running=0, peak=0, max_dd=0;
   int sl_hits=0, manual_exits=0;
   double sl_pnl=0, manual_pnl=0;

   for(int i = 0; i < total_deals; i++)
   {
      ulong t = HistoryDealGetTicket(i);
      if(HistoryDealGetString(t, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(t, DEAL_MAGIC) != InpMagic) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(t, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;

      double net    = HistoryDealGetDouble(t, DEAL_PROFIT)
                    + HistoryDealGetDouble(t, DEAL_SWAP)
                    + HistoryDealGetDouble(t, DEAL_COMMISSION);
      ENUM_DEAL_REASON reason = (ENUM_DEAL_REASON)HistoryDealGetInteger(t, DEAL_REASON);
      ENUM_DEAL_TYPE   dtype  = (ENUM_DEAL_TYPE)HistoryDealGetInteger(t, DEAL_TYPE);
      // dtype SELL = closing a BUY; dtype BUY = closing a SELL
      bool was_buy = (dtype == DEAL_TYPE_SELL);

      total_exits++;
      total_pnl  += net;
      running    += net;
      if(running > peak) peak = running;
      double dd   = peak - running;
      if(dd > max_dd) max_dd = dd;
      if(net > 0) gross_profit += net; else gross_loss += MathAbs(net);

      if(was_buy) { buy_pnl  += net; if(net > 0) n_buy_wins++;  else n_buy_losses++; }
      else        { sell_pnl += net; if(net > 0) n_sell_wins++; else n_sell_losses++; }

      if(reason == DEAL_REASON_SL)        { sl_hits++;      sl_pnl     += net; }
      else                                { manual_exits++; manual_pnl += net; }
   }

   if(total_exits == 0) { Print("[SUMMARY] No trades for this magic."); return; }

   double pf      = (gross_loss > 0) ? gross_profit / gross_loss : 99.0;
   double init_bal = TesterStatistics(STAT_INITIAL_DEPOSIT);
   double ret_pct  = (init_bal > 0) ? total_pnl / init_bal * 100.0 : 0;

   Print("======================================================================");
   Print("  WEEKEND GAP EA v5 STRADDLE - BACKTEST SUMMARY");
   Print("======================================================================");
   Print("  Initial balance:    $", DoubleToString(init_bal, 2));
   Print("  Net profit:         $", DoubleToString(total_pnl, 2), " (", DoubleToString(ret_pct,2), "%)");
   Print("  Max drawdown:       $", DoubleToString(max_dd, 2));
   Print("  Profit factor:      ",  DoubleToString(pf, 2));
   Print("");
   Print("--- SIDES (total exits: ", total_exits, ") ---");
   Print("  BUY  legs: wins=", n_buy_wins, " losses=", n_buy_losses, " PnL=$", DoubleToString(buy_pnl,2));
   Print("  SELL legs: wins=", n_sell_wins," losses=", n_sell_losses," PnL=$", DoubleToString(sell_pnl,2));
   Print("");
   Print("--- EXIT REASONS ---");
   Print("  SL hits:     n=", sl_hits,      " PnL=$", DoubleToString(sl_pnl, 2));
   Print("  Manual exit: n=", manual_exits, " PnL=$", DoubleToString(manual_pnl, 2));
   Print("");
   Print("  ONNX ML gate: ", InpUseML ? "ON" : "OFF");
   Print("  Min body:     ", DoubleToString(InpMinBodyPct,2), "%");
   Print("  SL each side: ", DoubleToString(FIXED_SL_PCT,2), "%");
   Print("  Lot/side:     ", DoubleToString(InpFixedLot,2));
   Print("  Magic:        ", InpMagic);
   Print("======================================================================");
}
