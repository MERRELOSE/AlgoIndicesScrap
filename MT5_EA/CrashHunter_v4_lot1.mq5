//+------------------------------------------------------------------+
//|                                              CrashHunter_v4.mq5  |
//|                         Behavior-Based Trading System             |
//|                         Crash 1000 Index - Optimized from MT5 BT  |
//+------------------------------------------------------------------+
#property copyright "AlgoIndicesScrap Project"
#property link      ""
#property version   "4.00"
#property description "Crash 1000 v4 - Optimized from real MT5 backtest results"
#property description "Removed losing signals, enforced H4 filter, adjusted trailing"

#include <Trade\Trade.mqh>

//+------------------------------------------------------------------+
//| INPUT PARAMETERS                                                  |
//+------------------------------------------------------------------+

// --- Risk Management ---
input double   InpLotSize        = 1.00;     // Lot size (1.0 for Crash 1000)
input double   InpSLMultiplier   = 1.5;      // Stop Loss (x ATR)
input double   InpTPMultiplier   = 3.0;      // Take Profit (x ATR)
input double   InpTrailStart     = 0.5;      // Trailing start (x ATR profit) - v4: lowered from 1.0
input double   InpTrailDistance  = 1.5;      // Trailing distance (x ATR) - v4: tighter from 2.0
input int      InpMaxTrades      = 1;        // Max open trades
input int      InpCooldownBars   = 4;        // Cooldown bars between trades (H1)

// --- Signal Parameters ---
input int      InpRSIPeriod      = 14;       // RSI Period
input int      InpRSIOversold    = 35;       // RSI Oversold threshold
input int      InpRSIDeepOS      = 20;       // RSI Deep Oversold (filter out)
input int      InpEMAFast        = 5;        // Fast EMA
input int      InpEMASlow        = 20;       // Slow EMA
input int      InpATRPeriod      = 14;       // ATR Period
input int      InpSpikeLookback  = 3;        // Bars to look back for crash spike
input double   InpSpikeThreshold = 3.0;      // Spike threshold (x std dev)
input int      InpConsecDown     = 3;        // Consecutive down candles for reversal

// --- Multi-Timeframe ---
input bool     InpUseH4Filter    = true;     // Use H4 trend filter
input int      InpH4RSILimit     = 40;       // H4 RSI below this = bearish (no trade)

// --- Time Filter ---
input int      InpMaxHoldBars    = 30;       // Max bars to hold a trade

//+------------------------------------------------------------------+
//| GLOBAL VARIABLES                                                  |
//+------------------------------------------------------------------+
CTrade         trade;
int            handleRSI;
int            handleRSI_H4;
int            handleEMAFast;
int            handleEMASlow;
int            handleATR;
int            handleEMAFast_H4;
int            handleEMASlow_H4;

int            lastTradeBar;     // bar index of last trade
int            openTradeBar;     // bar index when current trade opened
int            magicNumber = 31000;

//+------------------------------------------------------------------+
//| Expert initialization                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   // Set magic number
   trade.SetExpertMagicNumber(magicNumber);
   trade.SetDeviationInPoints(50);
   trade.SetTypeFilling(ORDER_FILLING_IOC);

   // Create indicator handles - H1
   handleRSI     = iRSI(_Symbol, PERIOD_H1, InpRSIPeriod, PRICE_CLOSE);
   handleEMAFast = iMA(_Symbol, PERIOD_H1, InpEMAFast, 0, MODE_EMA, PRICE_CLOSE);
   handleEMASlow = iMA(_Symbol, PERIOD_H1, InpEMASlow, 0, MODE_EMA, PRICE_CLOSE);
   handleATR     = iATR(_Symbol, PERIOD_H1, InpATRPeriod);

   // Create indicator handles - H4
   handleRSI_H4     = iRSI(_Symbol, PERIOD_H4, InpRSIPeriod, PRICE_CLOSE);
   handleEMAFast_H4 = iMA(_Symbol, PERIOD_H4, InpEMAFast, 0, MODE_EMA, PRICE_CLOSE);
   handleEMASlow_H4 = iMA(_Symbol, PERIOD_H4, InpEMASlow, 0, MODE_EMA, PRICE_CLOSE);

   if(handleRSI == INVALID_HANDLE || handleEMAFast == INVALID_HANDLE ||
      handleEMASlow == INVALID_HANDLE || handleATR == INVALID_HANDLE)
   {
      Print("Failed to create indicator handles");
      return INIT_FAILED;
   }

   lastTradeBar = 0;
   openTradeBar = 0;

   Print("CrashHunter v4 initialized | Symbol: ", _Symbol);
   Print("Settings: SL=", InpSLMultiplier, "xATR | TP=", InpTPMultiplier, "xATR | H4 Filter=", InpUseH4Filter);

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Check if new H1 bar formed                                       |
//+------------------------------------------------------------------+
bool IsNewBar()
{
   static datetime lastBarTime = 0;
   datetime currentBarTime = iTime(_Symbol, PERIOD_H1, 0);

   if(currentBarTime != lastBarTime)
   {
      lastBarTime = currentBarTime;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Count open positions for this EA                                  |
//+------------------------------------------------------------------+
int CountOpenPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
      {
         if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
            PositionGetInteger(POSITION_MAGIC) == magicNumber)
         {
            count++;
         }
      }
   }
   return count;
}

//+------------------------------------------------------------------+
//| Detect crash spike in recent bars                                 |
//+------------------------------------------------------------------+
bool DetectCrashSpike(int lookback)
{
   // Calculate rolling mean and std of returns
   double returns[];
   ArrayResize(returns, 100);

   for(int i = 0; i < 100; i++)
   {
      double close_i = iClose(_Symbol, PERIOD_H1, i);
      double close_prev = iClose(_Symbol, PERIOD_H1, i + 1);
      if(close_prev > 0)
         returns[i] = (close_i - close_prev) / close_prev;
      else
         returns[i] = 0;
   }

   // Mean and std
   double sum = 0, sum2 = 0;
   for(int i = 0; i < 100; i++)
   {
      sum += returns[i];
      sum2 += returns[i] * returns[i];
   }
   double mean = sum / 100;
   double std = MathSqrt(sum2 / 100 - mean * mean);

   if(std <= 0) return false;

   // Check recent bars for spike
   double threshold = mean - InpSpikeThreshold * std;

   for(int i = 1; i <= lookback; i++)
   {
      if(returns[i] < threshold)
         return true;
   }

   return false;
}

//+------------------------------------------------------------------+
//| Check if candle is a doji                                        |
//+------------------------------------------------------------------+
bool IsDoji(int shift)
{
   double open_val  = iOpen(_Symbol, PERIOD_H1, shift);
   double close_val = iClose(_Symbol, PERIOD_H1, shift);
   double high_val  = iHigh(_Symbol, PERIOD_H1, shift);
   double low_val   = iLow(_Symbol, PERIOD_H1, shift);

   double body = MathAbs(close_val - open_val);
   double range = high_val - low_val;

   if(range <= 0) return true;
   return (body / range) < 0.1;
}

//+------------------------------------------------------------------+
//| Count consecutive down candles                                    |
//+------------------------------------------------------------------+
int CountConsecDown()
{
   int count = 0;
   for(int i = 1; i <= 10; i++)
   {
      double close_i = iClose(_Symbol, PERIOD_H1, i);
      double close_prev = iClose(_Symbol, PERIOD_H1, i + 1);
      if(close_i < close_prev)
         count++;
      else
         break;
   }
   return count;
}

//+------------------------------------------------------------------+
//| Get H4 trend: 1=bullish, 0=neutral, -1=bearish                  |
//+------------------------------------------------------------------+
int GetH4Trend()
{
   if(!InpUseH4Filter) return 0;  // neutral if disabled

   double emaFast[], emaSlow[], rsi[];

   if(CopyBuffer(handleEMAFast_H4, 0, 0, 2, emaFast) < 2) return 0;
   if(CopyBuffer(handleEMASlow_H4, 0, 0, 2, emaSlow) < 2) return 0;
   if(CopyBuffer(handleRSI_H4, 0, 0, 2, rsi) < 2) return 0;

   // Bearish: EMA fast below slow AND RSI < limit
   if(emaFast[0] < emaSlow[0] && rsi[0] < InpH4RSILimit)
      return -1;

   // Bullish: EMA fast above slow
   if(emaFast[0] > emaSlow[0])
      return 1;

   return 0;
}

//+------------------------------------------------------------------+
//| Main signal detection - v3 logic                                  |
//+------------------------------------------------------------------+
bool DetectEntrySignal(string &signalName, double &signalScore)
{
   // Get indicator values
   double rsi[], emaFast[], emaSlow[], emaFastPrev[], emaSlowPrev[], atr[];

   if(CopyBuffer(handleRSI, 0, 1, 1, rsi) < 1) return false;
   if(CopyBuffer(handleEMAFast, 0, 1, 2, emaFast) < 2) return false;
   if(CopyBuffer(handleEMASlow, 0, 1, 2, emaSlow) < 2) return false;
   if(CopyBuffer(handleATR, 0, 1, 1, atr) < 1) return false;

   double currentRSI = rsi[0];
   double currentEMAFast = emaFast[1];  // current
   double currentEMASlow = emaSlow[1];
   double prevEMAFast = emaFast[0];     // previous
   double prevEMASlow = emaSlow[0];

   // Distance from EMA20
   double currentClose = iClose(_Symbol, PERIOD_H1, 1);
   double distEMA20 = 0;
   if(currentEMASlow > 0)
      distEMA20 = (currentClose - currentEMASlow) / currentEMASlow * 100;

   // Volatility ratio
   double vol5 = 0, vol20 = 0;
   double rets[];
   ArrayResize(rets, 20);
   for(int i = 0; i < 20; i++)
   {
      double c1 = iClose(_Symbol, PERIOD_H1, i + 1);
      double c2 = iClose(_Symbol, PERIOD_H1, i + 2);
      rets[i] = (c2 > 0) ? (c1 - c2) / c2 : 0;
   }

   // Calculate rolling std
   double sum5 = 0, sum5sq = 0, sum20 = 0, sum20sq = 0;
   for(int i = 0; i < 5; i++) { sum5 += rets[i]; sum5sq += rets[i]*rets[i]; }
   for(int i = 0; i < 20; i++) { sum20 += rets[i]; sum20sq += rets[i]*rets[i]; }
   vol5 = MathSqrt(sum5sq/5 - (sum5/5)*(sum5/5));
   vol20 = MathSqrt(sum20sq/20 - (sum20/20)*(sum20/20));
   double volRatio = (vol20 > 0) ? vol5 / vol20 : 1.0;

   // === FILTERS ===

   // Doji filter
   if(IsDoji(1))
   {
      signalName = "FILTER:doji";
      return false;
   }

   // Vol squeeze filter
   if(volRatio < 0.5)
   {
      signalName = "FILTER:squeeze";
      return false;
   }

   // H4 trend filter
   int h4Trend = GetH4Trend();
   if(h4Trend == -1)
   {
      signalName = "FILTER:h4_bearish";
      return false;
   }

   // === SIGNALS (LONG ONLY) - v4 OPTIMIZED FROM MT5 BACKTEST ===
   //
   // KEPT (profitable in backtest):
   //   rsi_os+consec_rev+h4_bull     60% WR  +$40  (BEST)
   //   rsi_os+consec_rev+overext     50% WR  +$26
   //   rsi_os+overext                78% WR  +$23  (best WR without H4)
   //   post_crash                    63% WR  +$18
   //   post_crash+h4_bull            40% WR  +$12  (volume signal)
   //
   // REMOVED (losing in backtest):
   //   rsi_os+overext+h4_bull        14% WR  -$28  (WORST - trap signal)
   //   rsi_os+consec_rev (no H4)     36% WR  -$5   (needs H4 to work)
   //   post_crash+consec_rev+h4_bull 20% WR  -$7
   //   post_crash+rsi_os (no other)  33% WR  -$6

   signalName = "";
   signalScore = 0;
   int signalCount = 0;
   bool hasStrongSignal = false;
   bool hasPostCrash = false;
   bool hasRSIOS = false;
   bool hasConsecRev = false;
   bool hasOverext = false;
   bool hasBullCross = false;
   bool hasH4Bull = (h4Trend == 1);

   // Detect individual conditions
   bool crashDetected = DetectCrashSpike(InpSpikeLookback);
   int consecDown = CountConsecDown();

   if(crashDetected)                                          hasPostCrash = true;
   if(currentRSI >= InpRSIDeepOS && currentRSI < InpRSIOversold) hasRSIOS = true;
   if(consecDown >= InpConsecDown && currentRSI > InpRSIDeepOS)  hasConsecRev = true;
   if(distEMA20 < -1.0 && distEMA20 > -3.0)                    hasOverext = true;
   if(currentEMAFast > currentEMASlow && prevEMAFast <= prevEMASlow) hasBullCross = true;

   // === v4 BLOCK: Kill the trap combo (rsi_os+overext+h4_bull = 14% WR) ===
   if(hasRSIOS && hasOverext && hasH4Bull && !hasPostCrash && !hasConsecRev)
   {
      signalName = "BLOCK:rsi_overext_h4_trap";
      return false;
   }

   // === v4 BLOCK: rsi_os+consec_rev WITHOUT H4 = loses (36% WR) ===
   if(hasRSIOS && hasConsecRev && !hasH4Bull && !hasPostCrash && !hasOverext)
   {
      signalName = "BLOCK:rsi_consec_no_h4";
      return false;
   }

   // === v4 BLOCK: post_crash+rsi_os alone = loses (33% WR) ===
   if(hasPostCrash && hasRSIOS && !hasConsecRev && !hasOverext && !hasH4Bull)
   {
      signalName = "BLOCK:postcrash_rsi_alone";
      return false;
   }

   // === v4 BLOCK: post_crash+consec_rev+h4_bull = loses (20% WR) ===
   if(hasPostCrash && hasConsecRev && hasH4Bull && !hasRSIOS && !hasOverext)
   {
      signalName = "BLOCK:postcrash_consec_h4";
      return false;
   }

   // === v4.1 BLOCK: post_crash+h4_bull ONLY (32% WR, -$8, 38 trades) ===
   // post_crash works BETTER when H4 is NOT bullish (67% vs 32%)
   // Only block when no other signal confirms (rsi/consec/overext/cross)
   if(hasPostCrash && hasH4Bull && !hasRSIOS && !hasConsecRev && !hasOverext && !hasBullCross)
   {
      signalName = "BLOCK:postcrash_h4bull_only";
      return false;
   }

   // === v4.1 BLOCK: post_crash+rsi_os+consec_rev+h4_bull (33% WR, -$19) ===
   if(hasPostCrash && hasRSIOS && hasConsecRev && hasH4Bull && !hasOverext)
   {
      signalName = "BLOCK:postcrash_rsi_consec_h4";
      return false;
   }

   // === v4.1 BLOCK: post_crash+rsi_os+consec_rev+overext no H4 (20% WR, -$6) ===
   if(hasPostCrash && hasRSIOS && hasConsecRev && hasOverext && !hasH4Bull)
   {
      signalName = "BLOCK:postcrash_rsi_consec_overext";
      return false;
   }

   // === v4.2 BLOCK: post_crash+rsi_os+h4_bull only (57% WR but -$15, big losses) ===
   // post_crash+rsi_os works when NO h4_bull (see post_crash+rsi_os+overext = +$2)
   // but with h4_bull and no other confirm = trap
   if(hasPostCrash && hasRSIOS && hasH4Bull && !hasConsecRev && !hasOverext && !hasBullCross)
   {
      signalName = "BLOCK:postcrash_rsi_h4_only";
      return false;
   }

   // === BUILD VALID SIGNALS ===

   // Post-crash recovery (63% WR standalone, 40% with H4)
   if(hasPostCrash)
   {
      signalName += "post_crash+";
      signalScore += 1.0;
      signalCount++;
      hasStrongSignal = true;
   }

   // RSI oversold
   if(hasRSIOS)
   {
      signalName += "rsi_os+";
      signalScore += 0.6;
      signalCount++;
   }

   // Consecutive down reversal
   if(hasConsecRev)
   {
      signalName += "consec_rev+";
      signalScore += 0.4;
      signalCount++;
   }

   // Overextended below EMA20
   if(hasOverext)
   {
      signalName += "overext+";
      signalScore += 0.3;
      signalCount++;
   }

   // Bullish EMA cross
   if(hasBullCross)
   {
      signalName += "bull_cross+";
      signalScore += 0.5;
      signalCount++;
   }

   // H4 bullish confirmation
   if(hasH4Bull && signalCount > 0)
   {
      signalName += "h4_bull+";
      signalScore += 0.3;
   }

   // Remove trailing +
   if(StringLen(signalName) > 0)
      signalName = StringSubstr(signalName, 0, StringLen(signalName) - 1);

   // === v4 ENTRY RULES ===
   // Strong signal (post_crash) can enter alone
   // RSI combos MUST have H4 bull or overext for confluence
   // Minimum 2 core signals for non-crash entries
   if(hasStrongSignal)
      return true;

   if(signalCount >= 2)
      return true;

   return false;
}

//+------------------------------------------------------------------+
//| Manage trailing stop for open positions                           |
//+------------------------------------------------------------------+
void ManageTrailingStop()
{
   double atr[];
   if(CopyBuffer(handleATR, 0, 1, 1, atr) < 1) return;
   double currentATR = atr[0];

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != magicNumber) continue;

      double entryPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double currentSL  = PositionGetDouble(POSITION_SL);
      double currentTP  = PositionGetDouble(POSITION_TP);
      double profit     = PositionGetDouble(POSITION_PROFIT);

      // Only for BUY positions
      if(PositionGetInteger(POSITION_TYPE) != POSITION_TYPE_BUY) continue;

      double currentPrice = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double profitDistance = currentPrice - entryPrice;

      // Activate trailing after InpTrailStart * ATR profit
      if(profitDistance > InpTrailStart * currentATR)
      {
         double newSL = currentPrice - InpTrailDistance * currentATR;

         // Only move SL up, never down
         if(newSL > currentSL + _Point)
         {
            trade.PositionModify(ticket, newSL, currentTP);
         }
      }

      // Time stop: close after max bars
      int barsOpen = Bars(_Symbol, PERIOD_H1) - openTradeBar;
      if(barsOpen >= InpMaxHoldBars)
      {
         trade.PositionClose(ticket);
         Print("TIME STOP: Closed after ", barsOpen, " bars");
      }
   }
}

//+------------------------------------------------------------------+
//| Expert tick function                                              |
//+------------------------------------------------------------------+
void OnTick()
{
   // Manage existing positions every tick
   if(CountOpenPositions() > 0)
      ManageTrailingStop();

   // Only check new signals on new H1 bar
   if(!IsNewBar()) return;

   int currentBar = Bars(_Symbol, PERIOD_H1);

   // Check cooldown
   if(currentBar - lastTradeBar < InpCooldownBars) return;

   // Check max trades
   if(CountOpenPositions() >= InpMaxTrades) return;

   // Detect signal
   string signalName;
   double signalScore;

   if(!DetectEntrySignal(signalName, signalScore))
   {
      // Log filter reasons (optional, comment out for cleaner backtest)
      // if(StringFind(signalName, "FILTER") >= 0) Print(signalName);
      return;
   }

   // === PLACE TRADE ===

   double atr[];
   if(CopyBuffer(handleATR, 0, 1, 1, atr) < 1) return;
   double currentATR = atr[0];

   double price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double sl = price - InpSLMultiplier * currentATR;
   double tp = price + InpTPMultiplier * currentATR;

   // v4: Wider TP for high-confidence signals
   if(signalScore >= 1.5)
      tp = price + (InpTPMultiplier + 1.5) * currentATR;  // 4.5x ATR for strong confluence
   else if(signalScore >= 1.0)
      tp = price + (InpTPMultiplier + 0.5) * currentATR;  // 3.5x ATR for post_crash

   // v4: Dynamic lot - bigger on best signals
   double lots = InpLotSize;
   if(signalScore >= 1.8)      // triple confluence + h4
      lots = InpLotSize * 1.5;
   else if(signalScore < 0.8)  // weak signal = smaller
      lots = InpLotSize * 0.7;

   // Normalize
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lots = MathMax(minLot, MathMin(maxLot, MathRound(lots / lotStep) * lotStep));

   // Place BUY order
   if(trade.Buy(lots, _Symbol, price, sl, tp, signalName))
   {
      Print(">>> BUY: ", signalName, " | Score=", DoubleToString(signalScore, 1),
            " | Price=", DoubleToString(price, _Digits),
            " | SL=", DoubleToString(sl, _Digits),
            " | TP=", DoubleToString(tp, _Digits),
            " | Lots=", DoubleToString(lots, 2));

      lastTradeBar = currentBar;
      openTradeBar = currentBar;
   }
   else
   {
      Print("BUY FAILED: ", trade.ResultRetcodeDescription(), " | Signal: ", signalName);
   }
}

//+------------------------------------------------------------------+
//| Trade event handler                                               |
//+------------------------------------------------------------------+
void OnTrade()
{
   // Log trade closures
   static int lastDeals = 0;

   if(HistorySelect(0, TimeCurrent()))
   {
      int totalDeals = HistoryDealsTotal();

      if(totalDeals > lastDeals)
      {
         for(int i = lastDeals; i < totalDeals; i++)
         {
            ulong dealTicket = HistoryDealGetTicket(i);
            if(HistoryDealGetString(dealTicket, DEAL_SYMBOL) == _Symbol &&
               HistoryDealGetInteger(dealTicket, DEAL_MAGIC) == magicNumber)
            {
               double dealProfit = HistoryDealGetDouble(dealTicket, DEAL_PROFIT);
               ENUM_DEAL_ENTRY dealEntry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(dealTicket, DEAL_ENTRY);

               if(dealEntry == DEAL_ENTRY_OUT)
               {
                  Print("<<< CLOSED: P&L = $", DoubleToString(dealProfit, 2));
               }
            }
         }
         lastDeals = totalDeals;
      }
   }
}

//+------------------------------------------------------------------+
//| OnDeinit - Print full summary when backtest ends                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(handleRSI);
   IndicatorRelease(handleRSI_H4);
   IndicatorRelease(handleEMAFast);
   IndicatorRelease(handleEMASlow);
   IndicatorRelease(handleATR);
   IndicatorRelease(handleEMAFast_H4);
   IndicatorRelease(handleEMASlow_H4);

   // Only print summary in tester
   if(!MQLInfoInteger(MQL_TESTER)) return;

   PrintSummaryReport();
}

//+------------------------------------------------------------------+
//| Full summary report at end of backtest                            |
//+------------------------------------------------------------------+
void PrintSummaryReport()
{
   if(!HistorySelect(0, TimeCurrent())) return;

   int totalDeals = HistoryDealsTotal();
   if(totalDeals == 0) return;

   // --- Collect all closed trades ---
   int totalTrades = 0;
   int wins = 0;
   int losses = 0;
   double grossProfit = 0;
   double grossLoss = 0;
   double totalProfit = 0;
   double maxWin = 0;
   double maxLoss = 0;
   double totalBarsHeld = 0;

   // Signal tracking
   string signalNames[];
   int    signalCounts[];
   double signalProfits[];
   int    signalWins[];
   int    signalTotal[];
   int    numSignals = 0;

   // Monthly tracking
   int    monthKeys[];
   double monthPnl[];
   int    monthTradeCount[];
   int    numMonths = 0;

   // Exit reason tracking
   int tpCount = 0, slCount = 0, trailCount = 0, timeCount = 0, otherCount = 0;
   double tpPnl = 0, slPnl = 0, trailPnl = 0, timePnl = 0;

   // Drawdown tracking
   double peakBalance = 0;
   double maxDrawdown = 0;
   double runningBalance = 0;

   // Consecutive tracking
   int currentWinStreak = 0, currentLossStreak = 0;
   int maxWinStreak = 0, maxLossStreak = 0;

   for(int i = 0; i < totalDeals; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(HistoryDealGetString(ticket, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != magicNumber) continue;

      ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(ticket, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_OUT) continue;

      double profit = HistoryDealGetDouble(ticket, DEAL_PROFIT);
      double swap = HistoryDealGetDouble(ticket, DEAL_SWAP);
      double commission = HistoryDealGetDouble(ticket, DEAL_COMMISSION);
      double netProfit = profit + swap + commission;
      string comment = HistoryDealGetString(ticket, DEAL_COMMENT);
      datetime dealTime = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);

      totalTrades++;
      totalProfit += netProfit;
      runningBalance += netProfit;

      // Peak & drawdown
      if(runningBalance > peakBalance) peakBalance = runningBalance;
      double dd = peakBalance - runningBalance;
      if(dd > maxDrawdown) maxDrawdown = dd;

      if(netProfit > 0)
      {
         wins++;
         grossProfit += netProfit;
         if(netProfit > maxWin) maxWin = netProfit;
         currentWinStreak++;
         if(currentWinStreak > maxWinStreak) maxWinStreak = currentWinStreak;
         currentLossStreak = 0;
      }
      else
      {
         losses++;
         grossLoss += MathAbs(netProfit);
         if(netProfit < maxLoss) maxLoss = netProfit;
         currentLossStreak++;
         if(currentLossStreak > maxLossStreak) maxLossStreak = currentLossStreak;
         currentWinStreak = 0;
      }

      // --- Signal tracking from order comment ---
      // Find the opening deal to get the signal name
      ulong posId = HistoryDealGetInteger(ticket, DEAL_POSITION_ID);
      string sigName = "unknown";
      for(int j = 0; j < totalDeals; j++)
      {
         ulong t2 = HistoryDealGetTicket(j);
         if(HistoryDealGetInteger(t2, DEAL_POSITION_ID) == posId &&
            (ENUM_DEAL_ENTRY)HistoryDealGetInteger(t2, DEAL_ENTRY) == DEAL_ENTRY_IN)
         {
            sigName = HistoryDealGetString(t2, DEAL_COMMENT);
            break;
         }
      }

      // Store signal stats
      int sigIdx = -1;
      for(int s = 0; s < numSignals; s++)
      {
         if(signalNames[s] == sigName) { sigIdx = s; break; }
      }
      if(sigIdx == -1)
      {
         numSignals++;
         ArrayResize(signalNames, numSignals);
         ArrayResize(signalCounts, numSignals);
         ArrayResize(signalProfits, numSignals);
         ArrayResize(signalWins, numSignals);
         ArrayResize(signalTotal, numSignals);
         sigIdx = numSignals - 1;
         signalNames[sigIdx] = sigName;
         signalCounts[sigIdx] = 0;
         signalProfits[sigIdx] = 0;
         signalWins[sigIdx] = 0;
         signalTotal[sigIdx] = 0;
      }
      signalCounts[sigIdx]++;
      signalProfits[sigIdx] += netProfit;
      signalTotal[sigIdx]++;
      if(netProfit > 0) signalWins[sigIdx]++;

      // --- Monthly tracking ---
      MqlDateTime dt;
      TimeToStruct(dealTime, dt);
      int monthKey = dt.year * 100 + dt.mon;  // e.g. 202507

      int mIdx = -1;
      for(int m = 0; m < numMonths; m++)
      {
         if(monthKeys[m] == monthKey) { mIdx = m; break; }
      }
      if(mIdx == -1)
      {
         numMonths++;
         ArrayResize(monthKeys, numMonths);
         ArrayResize(monthPnl, numMonths);
         ArrayResize(monthTradeCount, numMonths);
         mIdx = numMonths - 1;
         monthKeys[mIdx] = monthKey;
         monthPnl[mIdx] = 0;
         monthTradeCount[mIdx] = 0;
      }
      monthPnl[mIdx] += netProfit;
      monthTradeCount[mIdx]++;

      // --- Exit reason ---
      if(StringFind(comment, "tp") >= 0 || StringFind(comment, "TP") >= 0)
      { tpCount++; tpPnl += netProfit; }
      else if(StringFind(comment, "sl") >= 0 || StringFind(comment, "SL") >= 0)
      { slCount++; slPnl += netProfit; }
      else if(StringFind(comment, "TIME") >= 0)
      { timeCount++; timePnl += netProfit; }
      else
      { otherCount++; trailPnl += netProfit; }
   }

   if(totalTrades == 0) return;

   // === PRINT REPORT ===
   double winRate = (double)wins / totalTrades * 100;
   double profitFactor = (grossLoss > 0) ? grossProfit / grossLoss : 99;
   double avgWin = (wins > 0) ? grossProfit / wins : 0;
   double avgLoss = (losses > 0) ? grossLoss / losses : 0;
   double expectancy = (winRate/100 * avgWin) - ((100-winRate)/100 * avgLoss);
   double initialBal = TesterStatistics(STAT_INITIAL_DEPOSIT);
   double returnPct = (initialBal > 0) ? totalProfit / initialBal * 100 : 0;

   Print("======================================================================");
   Print("  CRASHHUNTER v4 - BACKTEST SUMMARY REPORT");
   Print("======================================================================");
   Print("");
   Print("--- PERFORMANCE ---");
   Print("  Initial Balance:    $", DoubleToString(initialBal, 2));
   Print("  Final Balance:      $", DoubleToString(initialBal + totalProfit, 2));
   Print("  Net Profit:         $", DoubleToString(totalProfit, 2));
   Print("  Return:             ", DoubleToString(returnPct, 2), "%");
   Print("  Max Drawdown:       $", DoubleToString(maxDrawdown, 2));
   Print("  Profit Factor:      ", DoubleToString(profitFactor, 2));
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
   Print("  Risk/Reward Ratio:  1:", DoubleToString(avgLoss > 0 ? avgWin/avgLoss : 0, 2));
   Print("");
   Print("--- EXIT REASONS ---");
   if(tpCount > 0) Print("  Take Profit:  ", tpCount, " trades | $", DoubleToString(tpPnl, 2));
   if(slCount > 0) Print("  Stop Loss:    ", slCount, " trades | $", DoubleToString(slPnl, 2));
   if(timeCount > 0) Print("  Time Stop:    ", timeCount, " trades | $", DoubleToString(timePnl, 2));
   if(otherCount > 0) Print("  Trail/Other:  ", otherCount, " trades | $", DoubleToString(trailPnl, 2));
   Print("");
   Print("--- SIGNAL PERFORMANCE ---");

   // Sort signals by profit (simple bubble sort)
   for(int a = 0; a < numSignals - 1; a++)
      for(int b = a + 1; b < numSignals; b++)
         if(signalProfits[b] > signalProfits[a])
         {
            string tmpN = signalNames[a]; signalNames[a] = signalNames[b]; signalNames[b] = tmpN;
            double tmpP = signalProfits[a]; signalProfits[a] = signalProfits[b]; signalProfits[b] = tmpP;
            int tmpC = signalCounts[a]; signalCounts[a] = signalCounts[b]; signalCounts[b] = tmpC;
            int tmpW = signalWins[a]; signalWins[a] = signalWins[b]; signalWins[b] = tmpW;
            int tmpT = signalTotal[a]; signalTotal[a] = signalTotal[b]; signalTotal[b] = tmpT;
         }

   for(int s = 0; s < numSignals; s++)
   {
      double sWR = (signalTotal[s] > 0) ? (double)signalWins[s] / signalTotal[s] * 100 : 0;
      string marker = (signalProfits[s] > 0) ? "PROFIT" : "LOSS";
      Print("  ", signalNames[s]);
      Print("    Trades=", signalCounts[s],
            " | WR=", DoubleToString(sWR, 0), "%",
            " | PnL=$", DoubleToString(signalProfits[s], 2),
            " | Avg=$", DoubleToString(signalProfits[s]/MathMax(1,signalCounts[s]), 2),
            " [", marker, "]");
   }

   Print("");
   Print("--- MONTHLY BREAKDOWN ---");
   int profitableMonths = 0;
   for(int m = 0; m < numMonths; m++)
   {
      int yr = monthKeys[m] / 100;
      int mn = monthKeys[m] % 100;
      string marker = (monthPnl[m] > 0) ? "+" : "-";
      Print("  ", yr, "-", (mn < 10 ? "0" : ""), mn,
            ": $", DoubleToString(monthPnl[m], 2),
            " (", monthTradeCount[m], " trades) ", marker);
      if(monthPnl[m] > 0) profitableMonths++;
   }
   Print("  Profitable Months: ", profitableMonths, "/", numMonths,
         " (", DoubleToString((double)profitableMonths/MathMax(1,numMonths)*100, 0), "%)");

   Print("");
   Print("--- SETTINGS USED ---");
   Print("  Lot Size:        ", InpLotSize);
   Print("  SL Multiplier:   ", InpSLMultiplier, " x ATR");
   Print("  TP Multiplier:   ", InpTPMultiplier, " x ATR");
   Print("  Trail Start:     ", InpTrailStart, " x ATR");
   Print("  Trail Distance:  ", InpTrailDistance, " x ATR");
   Print("  RSI Oversold:    ", InpRSIOversold);
   Print("  RSI Deep OS:     ", InpRSIDeepOS);
   Print("  EMA Fast/Slow:   ", InpEMAFast, "/", InpEMASlow);
   Print("  Consec Down:     ", InpConsecDown);
   Print("  H4 Filter:       ", InpUseH4Filter);
   Print("  Max Hold Bars:   ", InpMaxHoldBars);
   Print("  Cooldown Bars:   ", InpCooldownBars);

   Print("");
   Print("======================================================================");
   Print("  Copy everything above and send for analysis");
   Print("======================================================================");
}

//+------------------------------------------------------------------+
//| Tester event for optimization results                             |
//+------------------------------------------------------------------+
double OnTester()
{
   // Custom optimization criterion: Profit Factor * Sqrt(trades)
   double profitFactor = TesterStatistics(STAT_PROFIT_FACTOR);
   int totalTrades = (int)TesterStatistics(STAT_TRADES);
   double maxDD = TesterStatistics(STAT_EQUITY_DDREL_PERCENT);

   if(totalTrades < 20 || maxDD > 20) return 0;

   return profitFactor * MathSqrt(totalTrades);
}
//+------------------------------------------------------------------+
