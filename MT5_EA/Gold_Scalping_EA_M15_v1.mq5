//+------------------------------------------------------------------+
//|                              Gold_Scalping_EA_M15_v1.mq5          |
//|                       XAUUSD M15 Friday 20-23h UTC scalper        |
//|                       AlgoIndicesScrap Project                    |
//+------------------------------------------------------------------+
//  Behavioral analysis on XAUUSD M15 (3 years) revealed that
//  Fridays 20-23h UTC (dow_4 + h_5) is a MASSIVE edge zone for LONG
//  trades with R:R 2:1. Every top recipe OOS was built around this
//  pair of conditions.
//
//  Recipes implemented (all LONG, all require dow_4 + h_5 UTC):
//    MS1: ema50_slope_q3          → OOS WR 85.4% (41 trades)
//    MS2: atr_14_q3               → OOS WR 76.2% (21 trades)
//    MS3: pos_in_range_20_q4      → OOS WR 73.0% (37 trades)
//    MS4: sess_ny_0 (not NY)      → OOS WR 72.5% (51 trades)
//    MS5: bb_pos_q4               → OOS WR 70.0% (30 trades)
//    MS6: atr_14_q2               → OOS WR 62.7% (51 trades)
//
//  Base (dow_4 + h_5 only) : OOS WR 50.5% (200 trades) — already > breakeven 36%
//  Realized R:R target:      1.78 (after 2.5 pips spread cost)
//
//  NOTE: Shorts disabled (all short recipes below breakeven 36%).
//+------------------------------------------------------------------+
#property copyright "AlgoIndicesScrap"
#property version   "1.00"
#property description "XAUUSD M15 Friday 20-23h UTC scalper. R:R 2:1, long-only."
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//+------------------------------------------------------------------+
//| INPUTS                                                            |
//+------------------------------------------------------------------+
input group "=== Risk ==="
input double InpRiskPercent      = 0.5;    // % equity per trade
input double InpFixedLot         = 0.0;    // 0 = risk-based
input double InpTPatATR          = 2.0;    // TP distance in ATR
input double InpSLatATR          = 1.0;    // SL distance in ATR
input int    InpMaxSpreadPoints  = 50;     // Skip if spread > this
input int    InpMagic            = 780015;

input group "=== Schedule (UTC) ==="
input int    InpTradingDow       = 5;      // UTC day. FRIDAY = 5 in MT5 (0=Sun,1=Mon,2=Tue,3=Wed,4=Thu,5=Fri,6=Sat).
input int    InpHourStart        = 21;     // UTC hours (inclusive). v1.01: narrowed to 21h-22h (best Python WR = 64% at 21h)
input int    InpHourEnd          = 22;     // UTC hours (exclusive)
input int    InpServerGMTOffsetHours = 0;  // Your broker server time offset from UTC (Deriv usually 0; most EU brokers 2 winter / 3 summer).
                                            // CRITICAL: if wrong, the EA trades the wrong time window. Check a live bar timestamp in MT5 vs your UTC clock.

input group "=== Recipes (LONG only) ==="
input bool   InpEnableMS1 = true;  // ema50_slope_q3 (strongest: OOS 85%)
input bool   InpEnableMS2 = true;  // atr_14_q3
input bool   InpEnableMS3 = true;  // pos_in_range_20_q4
input bool   InpEnableMS4 = true;  // sess_ny_0 (hours outside 12-21 UTC)
input bool   InpEnableMS5 = true;  // bb_pos_q4
input bool   InpEnableMS6 = true;  // atr_14_q2
input bool   InpAllowBaseOnly = false; // v1.01: disabled by default. Base entries dominated early-hour signals and wasted cooldown on losers.

input group "=== Indicator periods ==="
input int    InpATRPeriod        = 14;
input int    InpBBPeriod         = 20;
input double InpBBStd            = 2.0;
input int    InpEMA50Period      = 50;
input int    InpPercentileWindow = 500;    // ~ 5 trading days on M15

input group "=== Trade mgmt ==="
input int    InpCooldownBars     = 20;     // v1.01: long enough to only take 1 trade per Friday window (avoids picking the worst early-hour signals)
input int    InpMaxPositions     = 1;
input bool   InpEnableTrailing   = false;
input double InpTrailStartR      = 1.0;
input double InpTrailATR         = 0.8;

input group "=== Logging ==="
input bool   InpLogSignals       = true;
input bool   InpLogSkips         = false;
input bool   InpPrintSummary     = true;

//+------------------------------------------------------------------+
//| GLOBALS                                                           |
//+------------------------------------------------------------------+
CTrade         g_trade;
CPositionInfo  g_pos;
int            g_atr_handle = INVALID_HANDLE;
int            g_bb_handle = INVALID_HANDLE;
int            g_ema50_handle = INVALID_HANDLE;
datetime       g_last_bar = 0;
int            g_last_trade_bar_idx = -9999;

//+------------------------------------------------------------------+
int OnInit()
{
   if(_Period != PERIOD_M15)
      Print("WARNING: Gold_Scalping_EA_M15 is designed for M15. Current TF: ", EnumToString(_Period));
   if(InpTradingDow != 5)
   {
      Print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!");
      PrintFormat("!!! WARNING: InpTradingDow=%d — expected 5 (Friday in MT5) !!!", InpTradingDow);
      Print("!!! 4=Thursday, 5=Friday, 6=Saturday. The Python analysis says  !!!");
      Print("!!! Friday = the edge zone. Set InpTradingDow=5 in the inputs.  !!!");
      Print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!");
   }

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_trade.SetMarginMode();
   g_trade.SetDeviationInPoints(20);

   g_atr_handle   = iATR(_Symbol, PERIOD_CURRENT, InpATRPeriod);
   g_bb_handle    = iBands(_Symbol, PERIOD_CURRENT, InpBBPeriod, 0, InpBBStd, PRICE_CLOSE);
   g_ema50_handle = iMA(_Symbol, PERIOD_CURRENT, InpEMA50Period, 0, MODE_EMA, PRICE_CLOSE);

   if(g_atr_handle == INVALID_HANDLE || g_bb_handle == INVALID_HANDLE ||
      g_ema50_handle == INVALID_HANDLE)
   {
      Print("ERROR: Failed to init indicator handles");
      return INIT_FAILED;
   }
   PrintFormat("=== Gold Scalping EA M15 v1.00 init ===");
   PrintFormat("  Symbol=%s TF=%s Magic=%d",
               _Symbol, EnumToString(_Period), InpMagic);
   PrintFormat("  Schedule: dow=%d hours=[%d-%d) UTC  |  Server->UTC offset = %d hours",
               InpTradingDow, InpHourStart, InpHourEnd, InpServerGMTOffsetHours);
   // Sanity print: show current bar in both server and UTC
   datetime s = iTime(_Symbol, PERIOD_CURRENT, 0);
   datetime u = s - (datetime)(InpServerGMTOffsetHours * 3600);
   PrintFormat("  Now: server=%s  |  converted UTC=%s",
               TimeToString(s, TIME_DATE|TIME_MINUTES),
               TimeToString(u, TIME_DATE|TIME_MINUTES));
   PrintFormat("  Risk=%.2f%% | R:R %.1f:%.1f | Max spread=%d pts",
               InpRiskPercent, InpTPatATR, InpSLatATR, InpMaxSpreadPoints);
   PrintFormat("  Recipes: MS1=%s MS2=%s MS3=%s MS4=%s MS5=%s MS6=%s  base-only=%s",
               InpEnableMS1 ? "Y" : "N", InpEnableMS2 ? "Y" : "N",
               InpEnableMS3 ? "Y" : "N", InpEnableMS4 ? "Y" : "N",
               InpEnableMS5 ? "Y" : "N", InpEnableMS6 ? "Y" : "N",
               InpAllowBaseOnly ? "Y" : "N");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(g_atr_handle != INVALID_HANDLE) IndicatorRelease(g_atr_handle);
   if(g_bb_handle != INVALID_HANDLE) IndicatorRelease(g_bb_handle);
   if(g_ema50_handle != INVALID_HANDLE) IndicatorRelease(g_ema50_handle);

   if(InpPrintSummary && MQLInfoInteger(MQL_TESTER))
      PrintSummaryReport();
}

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
//| Evaluate context (same feature layer as v1.20 Gold EA)            |
//+------------------------------------------------------------------+
struct Cond {
   bool   ok;
   bool   atr_q3, atr_q2;
   bool   bb_pos_q4;
   bool   pos_range_20_q4;
   bool   ema50_slope_q3;
   int    hour_utc, dow_mt5;
   bool   sess_ny_on;  // 12 <= h < 21
};

Cond Evaluate()
{
   Cond c;
   c.ok = false;
   int need = InpPercentileWindow + 60;
   double H[], L[], C[], A[], BU[], BD[], BM[], E50[];
   ArraySetAsSeries(H, true); ArraySetAsSeries(L, true); ArraySetAsSeries(C, true);
   ArraySetAsSeries(A, true); ArraySetAsSeries(BU, true); ArraySetAsSeries(BD, true);
   ArraySetAsSeries(BM, true); ArraySetAsSeries(E50, true);

   if(CopyHigh (_Symbol, PERIOD_CURRENT, 0, need, H) <= 0) return c;
   if(CopyLow  (_Symbol, PERIOD_CURRENT, 0, need, L) <= 0) return c;
   if(CopyClose(_Symbol, PERIOD_CURRENT, 0, need, C) <= 0) return c;
   if(CopyBuffer(g_atr_handle,    0, 0, need, A)    <= 0) return c;
   if(CopyBuffer(g_bb_handle,     1, 0, need, BU)   <= 0) return c;
   if(CopyBuffer(g_bb_handle,     2, 0, need, BD)   <= 0) return c;
   if(CopyBuffer(g_bb_handle,     0, 0, need, BM)   <= 0) return c;
   if(CopyBuffer(g_ema50_handle,  0, 0, need, E50)  <= 0) return c;

   int i = 1;
   if(A[i] <= 0 || BM[i] <= 0) return c;

   double atr_i        = A[i];
   double bb_pos_i     = (BU[i] - BD[i] > 0) ? (C[i] - BD[i]) / (BU[i] - BD[i]) : 0.5;
   // pos_in_range_20: price vs 20-bar hi/lo
   double hi20 = H[ArrayMaximum(H, i, 20)];
   double lo20 = L[ArrayMinimum(L, i, 20)];
   double pr20 = (hi20 - lo20 > 0) ? (C[i] - lo20) / (hi20 - lo20) : 0.5;
   // EMA50 slope: 20-bar diff / value
   double slope_i = (E50[i + 20] > 0) ? (E50[i] - E50[i + 20]) / E50[i + 20] : 0;

   // Build rolling series for percentile
   double s_atr[], s_bbp[], s_pr20[], s_slope[];
   ArrayResize(s_atr,   InpPercentileWindow);
   ArrayResize(s_bbp,   InpPercentileWindow);
   ArrayResize(s_pr20,  InpPercentileWindow);
   ArrayResize(s_slope, InpPercentileWindow);

   for(int k = 0; k < InpPercentileWindow; k++)
   {
      int j = i + k;
      s_atr[k] = A[j];
      s_bbp[k] = (BU[j] - BD[j] > 0) ? (C[j] - BD[j]) / (BU[j] - BD[j]) : 0.5;
      double hi_k = H[ArrayMaximum(H, j, 20)];
      double lo_k = L[ArrayMinimum(L, j, 20)];
      s_pr20[k] = (hi_k - lo_k > 0) ? (C[j] - lo_k) / (hi_k - lo_k) : 0.5;
      s_slope[k] = (E50[j + 20] > 0) ? (E50[j] - E50[j + 20]) / E50[j + 20] : 0;
   }

   double pr_atr    = PctileRank(s_atr,   InpPercentileWindow, atr_i);
   double pr_bbp    = PctileRank(s_bbp,   InpPercentileWindow, bb_pos_i);
   double pr_pr20   = PctileRank(s_pr20,  InpPercentileWindow, pr20);
   double pr_slope  = PctileRank(s_slope, InpPercentileWindow, slope_i);

   c.atr_q2         = (pr_atr   > 0.25 && pr_atr   <= 0.50);
   c.atr_q3         = (pr_atr   > 0.50 && pr_atr   <= 0.75);
   c.bb_pos_q4      = (pr_bbp   > 0.75);
   c.pos_range_20_q4 = (pr_pr20 > 0.75);
   c.ema50_slope_q3 = (pr_slope > 0.50 && pr_slope <= 0.75);

   // Convert bar server time to UTC using the user-provided broker offset
   datetime bar_server = iTime(_Symbol, PERIOD_CURRENT, i);
   datetime bar_utc = bar_server - (datetime)(InpServerGMTOffsetHours * 3600);
   MqlDateTime mdt;
   TimeToStruct(bar_utc, mdt);
   c.hour_utc = mdt.hour;
   c.dow_mt5  = mdt.day_of_week;  // 0=Sun in MT5 convention, Friday = 5
   c.sess_ny_on = (mdt.hour >= 12 && mdt.hour < 21);

   c.ok = true;
   return c;
}

//+------------------------------------------------------------------+
//| Recipe matcher                                                    |
//+------------------------------------------------------------------+
struct Match {
   bool   fire;
   string tag;
};

Match MatchRecipes(const Cond &c)
{
   Match m;
   m.fire = false;
   m.tag = "";

   // Hard base: day-of-week + hour window
   bool day_ok  = (c.dow_mt5 == InpTradingDow);
   bool hour_ok = (c.hour_utc >= InpHourStart && c.hour_utc < InpHourEnd);
   if(!day_ok || !hour_ok) return m;

   bool ms1 = InpEnableMS1 && c.ema50_slope_q3;
   bool ms2 = InpEnableMS2 && c.atr_q3;
   bool ms3 = InpEnableMS3 && c.pos_range_20_q4;
   bool ms4 = InpEnableMS4 && !c.sess_ny_on;  // sess_ny_0 = NOT in NY
   bool ms5 = InpEnableMS5 && c.bb_pos_q4;
   bool ms6 = InpEnableMS6 && c.atr_q2;

   if(ms1) m.tag += "MS1 ";
   if(ms2) m.tag += "MS2 ";
   if(ms3) m.tag += "MS3 ";
   if(ms4) m.tag += "MS4 ";
   if(ms5) m.tag += "MS5 ";
   if(ms6) m.tag += "MS6 ";

   bool any_specific = (ms1 || ms2 || ms3 || ms4 || ms5 || ms6);

   if(any_specific)
   {
      m.fire = true;
   }
   else if(InpAllowBaseOnly)
   {
      m.fire = true;
      m.tag = "BASE ";
   }
   return m;
}

void TryOpen()
{
   int total_bars = Bars(_Symbol, PERIOD_CURRENT);
   if(total_bars - g_last_trade_bar_idx < InpCooldownBars) return;

   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > InpMaxSpreadPoints)
   {
      if(InpLogSkips) PrintFormat("[SKIP] spread=%d > max=%d", (int)spread, InpMaxSpreadPoints);
      return;
   }

   if(CountMyPositions() >= InpMaxPositions) return;

   Cond c = Evaluate();
   if(!c.ok) return;

   Match m = MatchRecipes(c);
   if(!m.fire) return;

   double atr_buf[1];
   if(CopyBuffer(g_atr_handle, 0, 1, 1, atr_buf) <= 0) return;
   double atr_i = atr_buf[0];
   if(atr_i <= 0) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double entry = ask;
   double sl    = entry - InpSLatATR * atr_i;
   double tp    = entry + InpTPatATR * atr_i;

   double sl_dist = entry - sl;
   double lot = CalcLotByRisk(sl_dist);
   if(lot <= 0) return;

   string comment = StringFormat("GoldM15 %s", m.tag);
   if(InpLogSignals)
      PrintFormat("[SIGNAL] BUY | spread=%d | %s", (int)spread, m.tag);

   if(g_trade.Buy(lot, _Symbol, 0, sl, tp, comment))
   {
      g_last_trade_bar_idx = total_bars;
      if(InpLogSignals)
         PrintFormat("[OPEN OK] BUY lot=%.2f entry=%.2f SL=%.2f TP=%.2f (ATR=%.2f)",
                     lot, entry, sl, tp, atr_i);
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
      if(g_pos.PositionType() != POSITION_TYPE_BUY) continue;

      double entry = g_pos.PriceOpen();
      double sl = g_pos.StopLoss();
      double tp = g_pos.TakeProfit();
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double sl_dist = entry - sl;
      if(sl_dist <= 0) continue;
      double profit = bid - entry;
      if(profit < InpTrailStartR * sl_dist) continue;
      double new_sl = bid - InpTrailATR * atr;
      if(new_sl > sl + _Point) g_trade.PositionModify(g_pos.Ticket(), new_sl, tp);
   }
}

void OnTick()
{
   ManageTrailing();
   if(!IsNewBar()) return;
   TryOpen();
}

//+------------------------------------------------------------------+
//| Summary report (Journal at end of tester)                         |
//+------------------------------------------------------------------+
void PrintSummaryReport()
{
   if(!HistorySelect(0, TimeCurrent())) return;
   int totalDeals = HistoryDealsTotal();
   if(totalDeals == 0) return;

   int totalTrades = 0, wins = 0, losses = 0;
   double grossProfit = 0, grossLoss = 0, totalProfit = 0;
   double maxWin = 0, maxLoss = 0;
   int curWinStreak = 0, curLossStreak = 0;
   int maxWinStreak = 0, maxLossStreak = 0;
   double runBal = 0, peakBal = 0, maxDD = 0;

   string recipeNames[7] = {"MS1", "MS2", "MS3", "MS4", "MS5", "MS6", "BASE"};
   int    recipeCount[7] = {0,0,0,0,0,0,0};
   int    recipeWins[7]  = {0,0,0,0,0,0,0};
   double recipePnl[7]   = {0,0,0,0,0,0,0};
   int    recipeSoloCount[7] = {0,0,0,0,0,0,0};
   int    recipeSoloWins[7]  = {0,0,0,0,0,0,0};
   double recipeSoloPnl[7]   = {0,0,0,0,0,0,0};

   int tpCount = 0, slCount = 0, otherCount = 0;
   double tpPnl = 0, slPnl = 0, otherPnl = 0;

   int    monthKeys[]; double monthPnl[]; int monthTrades[]; int monthWins[]; int numMonths = 0;
   int    hourCount[24]; double hourPnl[24]; int hourWins[24];
   for(int h = 0; h < 24; h++) { hourCount[h] = 0; hourPnl[h] = 0; hourWins[h] = 0; }

   for(int i = 0; i < totalDeals; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(HistoryDealGetString(ticket, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != InpMagic) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;

      double net = HistoryDealGetDouble(ticket, DEAL_PROFIT)
                 + HistoryDealGetDouble(ticket, DEAL_SWAP)
                 + HistoryDealGetDouble(ticket, DEAL_COMMISSION);
      ENUM_DEAL_REASON reason = (ENUM_DEAL_REASON)HistoryDealGetInteger(ticket, DEAL_REASON);
      datetime exitTime = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);

      totalTrades++; totalProfit += net; runBal += net;
      if(runBal > peakBal) peakBal = runBal;
      double dd = peakBal - runBal; if(dd > maxDD) maxDD = dd;

      bool isWin = (net > 0);
      if(isWin) {
         wins++; grossProfit += net;
         if(net > maxWin) maxWin = net;
         curWinStreak++; if(curWinStreak > maxWinStreak) maxWinStreak = curWinStreak;
         curLossStreak = 0;
      } else {
         losses++; grossLoss += MathAbs(net);
         if(net < maxLoss) maxLoss = net;
         curLossStreak++; if(curLossStreak > maxLossStreak) maxLossStreak = curLossStreak;
         curWinStreak = 0;
      }

      if(reason == DEAL_REASON_TP)      { tpCount++; tpPnl += net; }
      else if(reason == DEAL_REASON_SL) { slCount++; slPnl += net; }
      else                              { otherCount++; otherPnl += net; }

      ulong posId = HistoryDealGetInteger(ticket, DEAL_POSITION_ID);
      string entryComment = "";
      datetime entryTime = 0;
      for(int j = 0; j < totalDeals; j++)
      {
         ulong t2 = HistoryDealGetTicket(j);
         if(HistoryDealGetInteger(t2, DEAL_POSITION_ID) == posId &&
            (ENUM_DEAL_ENTRY)HistoryDealGetInteger(t2, DEAL_ENTRY) == DEAL_ENTRY_IN)
         { entryComment = HistoryDealGetString(t2, DEAL_COMMENT);
           entryTime = (datetime)HistoryDealGetInteger(t2, DEAL_TIME); break; }
      }

      int matchedCount = 0;
      bool present[7] = {false,false,false,false,false,false,false};
      for(int r = 0; r < 7; r++)
      {
         if(StringFind(entryComment, recipeNames[r]) >= 0)
         { present[r] = true; matchedCount++; recipeCount[r]++; recipePnl[r] += net;
           if(isWin) recipeWins[r]++; }
      }
      if(matchedCount == 1)
         for(int r = 0; r < 7; r++) if(present[r])
         { recipeSoloCount[r]++; recipeSoloPnl[r] += net; if(isWin) recipeSoloWins[r]++; }

      // Monthly
      MqlDateTime dt; TimeToStruct(exitTime, dt);
      int monthKey = dt.year * 100 + dt.mon;
      int mIdx = -1;
      for(int m = 0; m < numMonths; m++) if(monthKeys[m] == monthKey) { mIdx = m; break; }
      if(mIdx == -1)
      {
         numMonths++;
         ArrayResize(monthKeys, numMonths); ArrayResize(monthPnl, numMonths);
         ArrayResize(monthTrades, numMonths); ArrayResize(monthWins, numMonths);
         mIdx = numMonths - 1;
         monthKeys[mIdx] = monthKey; monthPnl[mIdx] = 0;
         monthTrades[mIdx] = 0; monthWins[mIdx] = 0;
      }
      monthPnl[mIdx] += net; monthTrades[mIdx]++;
      if(isWin) monthWins[mIdx]++;

      if(entryTime > 0)
      {
         MqlDateTime edt; TimeToStruct(entryTime, edt);
         int h = edt.hour;
         if(h >= 0 && h < 24) { hourCount[h]++; hourPnl[h] += net; if(isWin) hourWins[h]++; }
      }
   }

   if(totalTrades == 0) { Print("No trades to report."); return; }

   double wr = (double)wins / totalTrades * 100.0;
   double pf = (grossLoss > 0) ? grossProfit / grossLoss : 99;
   double avgW = (wins > 0) ? grossProfit / wins : 0;
   double avgL = (losses > 0) ? grossLoss / losses : 0;
   double expectancy = (wr/100.0 * avgW) - ((100.0-wr)/100.0 * avgL);
   double initBal = TesterStatistics(STAT_INITIAL_DEPOSIT);
   double retPct = (initBal > 0) ? totalProfit / initBal * 100.0 : 0;
   double rrR = (avgL > 0) ? avgW / avgL : 0;

   Print("======================================================================");
   Print("  GOLD SCALPING EA M15 v1.00 - BACKTEST SUMMARY");
   Print("======================================================================");
   Print("");
   Print("--- PERFORMANCE ---");
   Print("  Initial Balance:    $", DoubleToString(initBal, 2));
   Print("  Final Balance:      $", DoubleToString(initBal + totalProfit, 2));
   Print("  Net Profit:         $", DoubleToString(totalProfit, 2));
   Print("  Return:             ", DoubleToString(retPct, 2), "%");
   Print("  Max Drawdown:       $", DoubleToString(maxDD, 2));
   Print("  Profit Factor:      ", DoubleToString(pf, 2));
   Print("  Expectancy/trade:   $", DoubleToString(expectancy, 2));
   Print("");
   Print("--- TRADES ---");
   Print("  Total Trades:       ", totalTrades);
   Print("  Winners:            ", wins, " (", DoubleToString(wr, 1), "%)");
   Print("  Losers:             ", losses, " (", DoubleToString(100-wr, 1), "%)");
   Print("  Avg Winner:         $", DoubleToString(avgW, 2));
   Print("  Avg Loser:          $", DoubleToString(avgL, 2));
   Print("  Best Trade:         $", DoubleToString(maxWin, 2));
   Print("  Worst Trade:        $", DoubleToString(maxLoss, 2));
   Print("  Max Win Streak:     ", maxWinStreak);
   Print("  Max Loss Streak:    ", maxLossStreak);
   Print("  Realized R:R:       1:", DoubleToString(rrR, 2));
   Print("");
   Print("--- EXIT REASONS ---");
   Print("  Take Profit:    ", tpCount, " trades | $", DoubleToString(tpPnl, 2));
   Print("  Stop Loss:      ", slCount, " trades | $", DoubleToString(slPnl, 2));
   Print("  Other:          ", otherCount, " trades | $", DoubleToString(otherPnl, 2));
   Print("");
   Print("--- RECIPE PERFORMANCE (all trades involving the recipe) ---");
   int order[7] = {0,1,2,3,4,5,6};
   for(int a = 0; a < 6; a++)
      for(int b = a + 1; b < 7; b++)
         if(recipePnl[order[b]] > recipePnl[order[a]])
         { int tmp = order[a]; order[a] = order[b]; order[b] = tmp; }
   for(int k = 0; k < 7; k++)
   {
      int r = order[k];
      if(recipeCount[r] == 0) continue;
      double rw = (double)recipeWins[r] / recipeCount[r] * 100.0;
      string mk = (recipePnl[r] > 0) ? "PROFIT" : "LOSS";
      Print("  ", recipeNames[r], "  n=", recipeCount[r],
            " | WR=", DoubleToString(rw, 1), "%",
            " | PnL=$", DoubleToString(recipePnl[r], 2),
            " | Avg=$", DoubleToString(recipePnl[r]/MathMax(1,recipeCount[r]), 2),
            "  [", mk, "]");
   }
   Print("");
   Print("--- RECIPE PERFORMANCE (SOLO) ---");
   for(int k = 0; k < 7; k++)
   {
      int r = order[k];
      if(recipeSoloCount[r] == 0) continue;
      double rw = (double)recipeSoloWins[r] / recipeSoloCount[r] * 100.0;
      string mk = (recipeSoloPnl[r] > 0) ? "PROFIT" : "LOSS";
      Print("  ", recipeNames[r], "  n=", recipeSoloCount[r],
            " | WR=", DoubleToString(rw, 1), "%",
            " | PnL=$", DoubleToString(recipeSoloPnl[r], 2),
            " | Avg=$", DoubleToString(recipeSoloPnl[r]/MathMax(1,recipeSoloCount[r]), 2),
            "  [", mk, "]");
   }
   Print("");

   // Sort months chronologically
   for(int a = 0; a < numMonths - 1; a++)
      for(int b = a + 1; b < numMonths; b++)
         if(monthKeys[b] < monthKeys[a])
         { int tK = monthKeys[a]; monthKeys[a] = monthKeys[b]; monthKeys[b] = tK;
           double tP = monthPnl[a]; monthPnl[a] = monthPnl[b]; monthPnl[b] = tP;
           int tT = monthTrades[a]; monthTrades[a] = monthTrades[b]; monthTrades[b] = tT;
           int tW = monthWins[a]; monthWins[a] = monthWins[b]; monthWins[b] = tW; }

   Print("--- MONTHLY BREAKDOWN ---");
   int profitable = 0; double cumul = initBal;
   for(int m = 0; m < numMonths; m++)
   {
      int yr = monthKeys[m] / 100;
      int mn = monthKeys[m] % 100;
      double mwr = (monthTrades[m] > 0) ? (double)monthWins[m] / monthTrades[m] * 100.0 : 0;
      cumul += monthPnl[m];
      string mk = (monthPnl[m] > 0) ? "+" : (monthPnl[m] < 0 ? "-" : "=");
      Print("  ", yr, "-", (mn < 10 ? "0" : ""), mn,
            " | PnL=$", DoubleToString(monthPnl[m], 2),
            " | trades=", monthTrades[m],
            " | WR=", DoubleToString(mwr, 0), "%",
            " | bal=$", DoubleToString(cumul, 2),
            "  ", mk);
      if(monthPnl[m] > 0) profitable++;
   }
   Print("  Profitable Months: ", profitable, "/", numMonths,
         " (", DoubleToString((double)profitable/MathMax(1,numMonths)*100.0, 0), "%)");
   Print("");
   Print("--- HOUR OF ENTRY (UTC) ---");
   for(int h = 0; h < 24; h++)
   {
      if(hourCount[h] == 0) continue;
      double hwr = (double)hourWins[h] / hourCount[h] * 100.0;
      double havg = hourPnl[h] / hourCount[h];
      Print("  ", (h<10?"0":""), h, "h: n=", hourCount[h],
            " | WR=", DoubleToString(hwr, 0), "%",
            " | PnL=$", DoubleToString(hourPnl[h], 2),
            " | Avg=$", DoubleToString(havg, 2));
   }
   Print("");
   Print("--- SETTINGS ---");
   Print("  Risk per trade:    ", DoubleToString(InpRiskPercent, 2), "%");
   Print("  TP/SL ATR:         ", DoubleToString(InpTPatATR, 1), " / ", DoubleToString(InpSLatATR, 1));
   Print("  Trading day (MT5): ", InpTradingDow, "  (0=Sun,1=Mon,...,5=Fri,6=Sat)");
   Print("  Trading hours UTC: [", InpHourStart, "-", InpHourEnd, ")");
   Print("  Recipes:           MS1=", InpEnableMS1?"Y":"N", " MS2=", InpEnableMS2?"Y":"N",
         " MS3=", InpEnableMS3?"Y":"N", " MS4=", InpEnableMS4?"Y":"N",
         " MS5=", InpEnableMS5?"Y":"N", " MS6=", InpEnableMS6?"Y":"N",
         "  base-only=", InpAllowBaseOnly?"Y":"N");
   Print("  Pctile window:     ", InpPercentileWindow, " bars");
   Print("  Cooldown:          ", InpCooldownBars, " bars");
   Print("  Trailing:          ", InpEnableTrailing?"ON":"OFF");
   Print("");
   Print("======================================================================");
   Print("  Copy everything above and paste into the chat for analysis");
   Print("======================================================================");
}

double OnTester()
{
   double pf = TesterStatistics(STAT_PROFIT_FACTOR);
   int n = (int)TesterStatistics(STAT_TRADES);
   if(n < 10) return 0;
   double dd = TesterStatistics(STAT_EQUITY_DDREL_PERCENT);
   return pf * MathSqrt(n) - dd * 0.1;
}
//+------------------------------------------------------------------+
