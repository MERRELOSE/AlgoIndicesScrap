//+------------------------------------------------------------------+
//|                                         CrashHunter_V100.mq5     |
//|                         Support/Resistance Trading System          |
//|                         Volatility 100 Index                       |
//+------------------------------------------------------------------+
//  Strategy: BUY at support + oversold, SELL at resistance + overbought
//  Backtested on Vol100:
//    SELL: Res3+ RSI>75 => PF=1.88, WR=74% (SL=3x, TP=2x)
//    BUY:  Sup4+ RSI<35 + H4 bull => 55.2% WR
//+------------------------------------------------------------------+
#property copyright "AlgoIndicesScrap Project"
#property version   "1.00"
#property description "CrashHunter V100 - Support/Resistance + RSI"
#property description "BUY at support, SELL at resistance"

#include <Trade\Trade.mqh>

//+------------------------------------------------------------------+
//| INPUT PARAMETERS                                                  |
//+------------------------------------------------------------------+
// Risk
input double   InpLotSize        = 1.00;     // Lot size (min for Vol 100)
input double   InpSL_Sell        = 3.0;      // SL SELL (x ATR)
input double   InpTP_Sell        = 2.0;      // TP SELL (x ATR)
input double   InpSL_Buy         = 2.0;      // SL BUY (x ATR)
input double   InpTP_Buy         = 2.5;      // TP BUY (x ATR)
input double   InpTrailStart     = 0.5;      // Trailing start (x ATR)
input double   InpTrailDist      = 1.0;      // Trailing distance (x ATR)
input int      InpMaxTrades      = 1;        // Max open trades
input int      InpCooldownBars   = 4;        // Cooldown bars (H1)

// Indicators
input int      InpRSIPeriod      = 14;       // RSI Period
input int      InpEMAFast        = 5;        // Fast EMA
input int      InpEMASlow        = 20;       // Slow EMA
input int      InpATRPeriod      = 14;       // ATR Period

// S/R Parameters
input int      InpSwingLookback  = 300;      // Bars to look back for swing points
input int      InpMinSupStr      = 4;        // Min support strength for BUY
input int      InpMinResStr      = 3;        // Min resistance strength for SELL
input int      InpRSIOverbought  = 75;       // RSI overbought for SELL
input int      InpRSIOversold    = 35;       // RSI oversold for BUY

// Time
input int      InpMaxHoldBars    = 25;       // Max bars to hold

//+------------------------------------------------------------------+
//| GLOBALS                                                            |
//+------------------------------------------------------------------+
CTrade         trade;

int            handleRSI, handleRSI_H4;
int            handleEMAFast, handleEMASlow;
int            handleATR;
int            handleEMAFast_H4, handleEMASlow_H4;

int            lastTradeBar;
int            openTradeBar;
int            magicNumber = 31000;   // Unique: Vol 100

string         lastExitReason = "";
int            lastExitBar = 0;
int            consecutiveLosses = 0;

// Swing point arrays
double         swingHighPrices[];
int            swingHighBars[];
int            numSwingHighs = 0;

double         swingLowPrices[];
int            swingLowBars[];
int            numSwingLows = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(magicNumber);

   handleRSI        = iRSI(_Symbol, PERIOD_H1, InpRSIPeriod, PRICE_CLOSE);
   handleRSI_H4     = iRSI(_Symbol, PERIOD_H4, InpRSIPeriod, PRICE_CLOSE);
   handleEMAFast    = iMA(_Symbol, PERIOD_H1, InpEMAFast, 0, MODE_EMA, PRICE_CLOSE);
   handleEMASlow    = iMA(_Symbol, PERIOD_H1, InpEMASlow, 0, MODE_EMA, PRICE_CLOSE);
   handleATR        = iATR(_Symbol, PERIOD_H1, InpATRPeriod);
   handleEMAFast_H4 = iMA(_Symbol, PERIOD_H4, InpEMAFast, 0, MODE_EMA, PRICE_CLOSE);
   handleEMASlow_H4 = iMA(_Symbol, PERIOD_H4, InpEMASlow, 0, MODE_EMA, PRICE_CLOSE);

   if(handleRSI == INVALID_HANDLE || handleATR == INVALID_HANDLE ||
      handleEMAFast == INVALID_HANDLE || handleEMASlow == INVALID_HANDLE)
   {
      Print("Failed to create indicator handles");
      return INIT_FAILED;
   }

   Print("=== CrashHunter V100 | Magic=", magicNumber,
         " | SELL: SL=", InpSL_Sell, "x TP=", InpTP_Sell, "x",
         " | BUY: SL=", InpSL_Buy, "x TP=", InpTP_Buy, "x ===");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
int CountOpenPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
         if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == magicNumber)
            count++;
   }
   return count;
}

//+------------------------------------------------------------------+
bool IsNewBar()
{
   static datetime lastBarTime = 0;
   datetime currentBarTime = iTime(_Symbol, PERIOD_H1, 0);
   if(currentBarTime != lastBarTime)
   { lastBarTime = currentBarTime; return true; }
   return false;
}

//+------------------------------------------------------------------+
//| Update swing highs and lows                                        |
//+------------------------------------------------------------------+
void UpdateSwingPoints()
{
   // Reset arrays
   numSwingHighs = 0;
   numSwingLows = 0;
   ArrayResize(swingHighPrices, 0);
   ArrayResize(swingHighBars, 0);
   ArrayResize(swingLowPrices, 0);
   ArrayResize(swingLowBars, 0);

   int lookback = InpSwingLookback;

   for(int i = 3; i < lookback - 2; i++)
   {
      double hi = iHigh(_Symbol, PERIOD_H1, i);
      double lo = iLow(_Symbol, PERIOD_H1, i);

      // Swing high: higher than 2 bars on each side
      if(hi >= iHigh(_Symbol, PERIOD_H1, i-1) && hi >= iHigh(_Symbol, PERIOD_H1, i-2) &&
         hi >= iHigh(_Symbol, PERIOD_H1, i+1) && hi >= iHigh(_Symbol, PERIOD_H1, i+2))
      {
         numSwingHighs++;
         ArrayResize(swingHighPrices, numSwingHighs);
         ArrayResize(swingHighBars, numSwingHighs);
         swingHighPrices[numSwingHighs-1] = hi;
         swingHighBars[numSwingHighs-1] = i;
      }

      // Swing low: lower than 2 bars on each side
      if(lo <= iLow(_Symbol, PERIOD_H1, i-1) && lo <= iLow(_Symbol, PERIOD_H1, i-2) &&
         lo <= iLow(_Symbol, PERIOD_H1, i+1) && lo <= iLow(_Symbol, PERIOD_H1, i+2))
      {
         numSwingLows++;
         ArrayResize(swingLowPrices, numSwingLows);
         ArrayResize(swingLowBars, numSwingLows);
         swingLowPrices[numSwingLows-1] = lo;
         swingLowBars[numSwingLows-1] = i;
      }
   }
}

//+------------------------------------------------------------------+
//| Count how many swing points are near a price level                 |
//+------------------------------------------------------------------+
int GetSupportStrength(double price, double atr)
{
   int count = 0;
   for(int i = 0; i < numSwingLows; i++)
   {
      if(MathAbs(swingLowPrices[i] - price) < atr)
         count++;
   }
   return count;
}

int GetResistanceStrength(double price, double atr)
{
   int count = 0;
   for(int i = 0; i < numSwingHighs; i++)
   {
      if(MathAbs(swingHighPrices[i] - price) < atr)
         count++;
   }
   return count;
}

//+------------------------------------------------------------------+
//| Detect signals                                                     |
//+------------------------------------------------------------------+
bool DetectSignal(string &signalName, double &signalScore, bool &isBuySignal)
{
   signalName = "";
   signalScore = 0;
   isBuySignal = false;

   double rsi[], emaFast[], emaSlow[], atr[];
   double emaFastH4[], emaSlowH4[];

   if(CopyBuffer(handleRSI, 0, 1, 1, rsi) < 1) return false;
   if(CopyBuffer(handleEMAFast, 0, 1, 1, emaFast) < 1) return false;
   if(CopyBuffer(handleEMASlow, 0, 1, 1, emaSlow) < 1) return false;
   if(CopyBuffer(handleATR, 0, 1, 1, atr) < 1) return false;
   if(CopyBuffer(handleEMAFast_H4, 0, 0, 1, emaFastH4) < 1) return false;
   if(CopyBuffer(handleEMASlow_H4, 0, 0, 1, emaSlowH4) < 1) return false;

   double price = iClose(_Symbol, PERIOD_H1, 1);
   double currentATR = atr[0];
   bool h4Bull = (emaFastH4[0] > emaSlowH4[0]);

   // Previous candle info
   double prevBody = iClose(_Symbol, PERIOD_H1, 2) - iOpen(_Symbol, PERIOD_H1, 2);
   bool prevRed = (prevBody < 0);

   // Consecutive candles
   int consecUp = 0;
   for(int i = 1; i <= 10; i++)
   {
      if(iClose(_Symbol, PERIOD_H1, i) > iClose(_Symbol, PERIOD_H1, i+1))
         consecUp++;
      else break;
   }

   int consecDown = 0;
   for(int i = 1; i <= 10; i++)
   {
      if(iClose(_Symbol, PERIOD_H1, i) < iClose(_Symbol, PERIOD_H1, i+1))
         consecDown++;
      else break;
   }

   // Get S/R strength
   int supStr = GetSupportStrength(price, currentATR);
   int resStr = GetResistanceStrength(price, currentATR);

   // Distance from EMA20
   double distEMA = (price - emaSlow[0]) / emaSlow[0] * 100;

   // ===== SELL SIGNALS (at resistance) =====

   // SELL 1: Res3+ + RSI>75 + red prev candle (60.8% DN, +10.2% edge, best signal)
   if(resStr >= InpMinResStr && rsi[0] > InpRSIOverbought && prevRed)
   {
      signalName = "V1.RES.RSI.RED";
      signalScore = 2.0;
      isBuySignal = false;
      return true;
   }

   // BLOCKED: V1.RES.RSI.DIST (-$164, 43% WR in backtest)

   // SELL 2: Res3+ + RSI>75 + consec2+ (56.3% DN, +5.6% edge)
   if(resStr >= InpMinResStr && rsi[0] > InpRSIOverbought && consecUp >= 2)
   {
      signalName = "V1.RES.RSI.CUP";
      signalScore = 1.5;
      isBuySignal = false;
      return true;
   }

   // SELL 4: Res5+ + RSI>70 + dist>0.3% (57.1% DN, +6.5% edge, 912 trades)
   if(resStr >= 5 && rsi[0] > 70 && distEMA > 0.3)
   {
      signalName = "V1.RES5.RSI70";
      signalScore = 1.3;
      isBuySignal = false;
      return true;
   }

   // SELL 5: Res4+ + RSI>70 + consec3+ (56.3% DN, stable across years)
   if(resStr >= 4 && rsi[0] > 70 && consecUp >= 3)
   {
      signalName = "V1.RES4.CUP3";
      signalScore = 1.2;
      isBuySignal = false;
      return true;
   }

   // ===== BUY SIGNALS (at support) =====

   // BUY 1: Sup3+ + RSI<30 + H4 bullish (55.5% UP, +6.1% edge, stable)
   if(supStr >= 3 && rsi[0] < 30 && h4Bull)
   {
      signalName = "V1.SUP.RSI30.H4";
      signalScore = 1.8;
      isBuySignal = true;
      return true;
   }

   // BUY 2: Sup4+ + RSI<35 + H4 bullish (55.2% UP, +5.9% edge)
   if(supStr >= InpMinSupStr && rsi[0] < InpRSIOversold && h4Bull)
   {
      signalName = "V1.SUP4.RSI35.H4";
      signalScore = 1.5;
      isBuySignal = true;
      return true;
   }

   // BLOCKED: V1.SUP4.RSI30.CDN (-$32, 43% WR in backtest)

   return false;
}

//+------------------------------------------------------------------+
//| Manage trailing stop + BE                                          |
//+------------------------------------------------------------------+
void ManagePositions()
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
      double profit      = PositionGetDouble(POSITION_PROFIT);
      long posType = PositionGetInteger(POSITION_TYPE);

      if(posType == POSITION_TYPE_BUY)
      {
         double currentPrice = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         double profitDist = currentPrice - entryPrice;

         // BE: once 0.5x ATR in profit, move SL to entry
         if(profitDist > 0.5 * currentATR && currentSL < entryPrice - _Point)
         {
            trade.PositionModify(ticket, entryPrice + 2 * _Point, currentTP);
         }

         // Trailing after BE
         if(profitDist > InpTrailStart * currentATR && currentSL >= entryPrice)
         {
            double newSL = currentPrice - InpTrailDist * currentATR;
            if(newSL > currentSL + _Point)
               trade.PositionModify(ticket, newSL, currentTP);
         }
      }
      else if(posType == POSITION_TYPE_SELL)
      {
         double currentPrice = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         double profitDist = entryPrice - currentPrice;

         // BE: once 0.5x ATR in profit, move SL to entry
         if(profitDist > 0.5 * currentATR && currentSL > entryPrice + _Point)
         {
            trade.PositionModify(ticket, entryPrice - 2 * _Point, currentTP);
         }

         // Trailing after BE
         if(profitDist > InpTrailStart * currentATR && currentSL <= entryPrice)
         {
            double newSL = currentPrice + InpTrailDist * currentATR;
            if(newSL < currentSL - _Point)
               trade.PositionModify(ticket, newSL, currentTP);
         }
      }

      // Time stop
      int barsOpen = Bars(_Symbol, PERIOD_H1) - openTradeBar;
      if(barsOpen >= InpMaxHoldBars)
      {
         trade.PositionClose(ticket);
         Print("TIME STOP: Closed after ", barsOpen, " bars | P&L=$", DoubleToString(profit, 2));
      }
   }
}

//+------------------------------------------------------------------+
void OnTick()
{
   if(CountOpenPositions() > 0)
   {
      ManagePositions();
      return;
   }

   if(!IsNewBar()) return;

   int currentBar = Bars(_Symbol, PERIOD_H1);

   // Filtre heures toxiques (02=11%, 04=33%, 05=33%)
   MqlDateTime timeNow;
   TimeCurrent(timeNow);
   if(timeNow.hour == 2 || timeNow.hour == 4 || timeNow.hour == 5)
      return;

   if(CountOpenPositions() >= InpMaxTrades) return;

   // Loss streak breaker
   if(consecutiveLosses >= 3)
   {
      if(currentBar - lastExitBar < 8) return;
      consecutiveLosses = 0;
   }

   // Cooldown
   if(currentBar - lastTradeBar < InpCooldownBars) return;

   if(lastExitReason == "SL" && lastExitBar > 0)
   {
      if(currentBar - lastExitBar < InpCooldownBars + 2) return;
   }

   // Update swing points
   UpdateSwingPoints();

   // Detect signal
   string signalName;
   double signalScore;
   bool isBuy;

   if(!DetectSignal(signalName, signalScore, isBuy)) return;

   // Get ATR
   double atr[];
   if(CopyBuffer(handleATR, 0, 1, 1, atr) < 1) return;
   double currentATR = atr[0];

   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double lots = MathMax(minLot, MathMin(maxLot, MathRound(InpLotSize / lotStep) * lotStep));

   // Get S/R for logging
   double price1 = iClose(_Symbol, PERIOD_H1, 1);
   int supStr = GetSupportStrength(price1, currentATR);
   int resStr = GetResistanceStrength(price1, currentATR);

   double rsi[];
   CopyBuffer(handleRSI, 0, 1, 1, rsi);

   if(isBuy)
   {
      double price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double sl = price - InpSL_Buy * currentATR;
      double tp = price + InpTP_Buy * currentATR;

      if(trade.Buy(lots, _Symbol, price, sl, tp, signalName))
      {
         Print(">>> BUY: ", signalName,
               " | SupStr=", supStr,
               " | RSI=", DoubleToString(rsi[0], 1),
               " | Price=", DoubleToString(price, _Digits),
               " | SL=", DoubleToString(sl, _Digits),
               " | TP=", DoubleToString(tp, _Digits));
         lastTradeBar = currentBar;
         openTradeBar = currentBar;
      }
      else
         Print("BUY FAILED: ", trade.ResultRetcodeDescription(), " | ", signalName);
   }
   else
   {
      double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double sl = price + InpSL_Sell * currentATR;
      double tp = price - InpTP_Sell * currentATR;

      if(trade.Sell(lots, _Symbol, price, sl, tp, signalName))
      {
         Print(">>> SELL: ", signalName,
               " | ResStr=", resStr,
               " | RSI=", DoubleToString(rsi[0], 1),
               " | Price=", DoubleToString(price, _Digits),
               " | SL=", DoubleToString(sl, _Digits),
               " | TP=", DoubleToString(tp, _Digits));
         lastTradeBar = currentBar;
         openTradeBar = currentBar;
      }
      else
         Print("SELL FAILED: ", trade.ResultRetcodeDescription(), " | ", signalName);
   }
}

//+------------------------------------------------------------------+
void OnTrade()
{
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
                  lastExitBar = Bars(_Symbol, PERIOD_H1);
                  int barsHeld = lastExitBar - openTradeBar;

                  if(dealProfit > 0)
                  { lastExitReason = "TP"; consecutiveLosses = 0; }
                  else
                  { lastExitReason = "SL"; consecutiveLosses++; }

                  ulong posId = HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID);
                  string sig = "";
                  for(int j = 0; j < totalDeals; j++)
                  {
                     ulong t = HistoryDealGetTicket(j);
                     if(HistoryDealGetInteger(t, DEAL_POSITION_ID) == posId &&
                        (ENUM_DEAL_ENTRY)HistoryDealGetInteger(t, DEAL_ENTRY) == DEAL_ENTRY_IN)
                     { sig = HistoryDealGetString(t, DEAL_COMMENT); break; }
                  }

                  Print("<<< EXIT [", lastExitReason, "]: P&L=$", DoubleToString(dealProfit, 2),
                        " | Signal=", sig,
                        " | Bars=", barsHeld,
                        " | ConsecLoss=", consecutiveLosses,
                        " | Bal=$", DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2));
               }
            }
         }
         lastDeals = totalDeals;
      }
   }
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   PrintSummaryReport();
}

//+------------------------------------------------------------------+
void PrintSummaryReport()
{
   if(!HistorySelect(0, TimeCurrent())) return;
   int totalDeals = HistoryDealsTotal();
   if(totalDeals == 0) return;

   int totalTrades=0, wins=0, losses=0;
   double grossProfit=0, grossLoss=0, totalProfit=0;
   double maxWin=0, maxLoss=0;
   int maxWS=0, maxLS=0, cWS=0, cLS=0;

   string sigNames[]; int sigCounts[], sigWins[];
   double sigPnl[]; int numSigs=0;

   string mKeys[]; double mPnl[]; int mCount[]; int numM=0;

   int buyCount=0, sellCount=0;
   double buyPnl=0, sellPnl=0;

   for(int i = 0; i < totalDeals; i++)
   {
      ulong tk = HistoryDealGetTicket(i);
      if(HistoryDealGetString(tk, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(tk, DEAL_MAGIC) != magicNumber) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(tk, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;

      double np = HistoryDealGetDouble(tk, DEAL_PROFIT) + HistoryDealGetDouble(tk, DEAL_SWAP) + HistoryDealGetDouble(tk, DEAL_COMMISSION);
      totalTrades++; totalProfit += np;

      if(np > 0) { wins++; grossProfit+=np; if(np>maxWin)maxWin=np; cWS++; cLS=0; if(cWS>maxWS)maxWS=cWS; }
      else { losses++; grossLoss+=MathAbs(np); if(np<maxLoss)maxLoss=np; cLS++; cWS=0; if(cLS>maxLS)maxLS=cLS; }

      // BUY or SELL?
      long dealType = HistoryDealGetInteger(tk, DEAL_TYPE);
      if(dealType == DEAL_TYPE_SELL) { buyCount++; buyPnl += np; }  // closing a BUY = SELL deal
      else if(dealType == DEAL_TYPE_BUY) { sellCount++; sellPnl += np; }  // closing a SELL = BUY deal

      // Signal tracking
      ulong posId = HistoryDealGetInteger(tk, DEAL_POSITION_ID);
      string comment = "";
      for(int j = 0; j < totalDeals; j++)
      { ulong t = HistoryDealGetTicket(j); if(HistoryDealGetInteger(t, DEAL_POSITION_ID)==posId && (ENUM_DEAL_ENTRY)HistoryDealGetInteger(t,DEAL_ENTRY)==DEAL_ENTRY_IN) { comment = HistoryDealGetString(t, DEAL_COMMENT); break; } }
      if(comment=="") comment="unknown";
      int sIdx=-1;
      for(int s=0; s<numSigs; s++) { if(sigNames[s]==comment) { sIdx=s; break; } }
      if(sIdx<0)
      {
         numSigs++; ArrayResize(sigNames,numSigs); ArrayResize(sigCounts,numSigs); ArrayResize(sigWins,numSigs); ArrayResize(sigPnl,numSigs);
         sIdx=numSigs-1; sigNames[sIdx]=comment; sigCounts[sIdx]=0; sigWins[sIdx]=0; sigPnl[sIdx]=0;
      }
      sigCounts[sIdx]++; sigPnl[sIdx]+=np; if(np>0) sigWins[sIdx]++;

      // Monthly
      MqlDateTime dt; TimeToStruct((datetime)HistoryDealGetInteger(tk, DEAL_TIME), dt);
      string mKey = StringFormat("%04d-%02d", dt.year, dt.mon);
      int mIdx=-1;
      for(int m=0; m<numM; m++) { if(mKeys[m]==mKey) { mIdx=m; break; } }
      if(mIdx<0)
      { numM++; ArrayResize(mKeys,numM); ArrayResize(mPnl,numM); ArrayResize(mCount,numM); mIdx=numM-1; mKeys[mIdx]=mKey; mPnl[mIdx]=0; mCount[mIdx]=0; }
      mPnl[mIdx]+=np; mCount[mIdx]++;
   }

   double pf = (grossLoss>0) ? grossProfit/grossLoss : 0;
   double exp = (totalTrades>0) ? totalProfit/totalTrades : 0;
   double avgW = (wins>0) ? grossProfit/wins : 0;
   double avgL = (losses>0) ? grossLoss/losses : 0;

   Print("======================================================================");
   Print("  CRASHHUNTER V100 - BACKTEST SUMMARY");
   Print("======================================================================");
   Print("");
   Print("--- PERFORMANCE ---");
   Print("  Net Profit:    $", DoubleToString(totalProfit, 2));
   Print("  Profit Factor: ", DoubleToString(pf, 2));
   Print("  Expectancy:    $", DoubleToString(exp, 2));
   Print("");
   Print("--- TRADES ---");
   Print("  Total:    ", totalTrades);
   Print("  Winners:  ", wins, " (", DoubleToString((totalTrades>0)?(double)wins/totalTrades*100:0, 1), "%)");
   Print("  Losers:   ", losses, " (", DoubleToString((totalTrades>0)?(double)losses/totalTrades*100:0, 1), "%)");
   Print("  Avg Win:  $", DoubleToString(avgW, 2));
   Print("  Avg Loss: $-", DoubleToString(avgL, 2));
   Print("  Best:     $", DoubleToString(maxWin, 2));
   Print("  Worst:    $", DoubleToString(maxLoss, 2));
   Print("  MaxWS:    ", maxWS, " | MaxLS: ", maxLS);
   Print("");
   Print("--- DIRECTION ---");
   Print("  BUY trades:  ", buyCount, " | PnL=$", DoubleToString(buyPnl, 2));
   Print("  SELL trades: ", sellCount, " | PnL=$", DoubleToString(sellPnl, 2));
   Print("");
   Print("--- SIGNAL PERFORMANCE ---");
   for(int s=0; s<numSigs; s++)
   {
      double wr = (sigCounts[s]>0) ? (double)sigWins[s]/sigCounts[s]*100 : 0;
      string tag = (sigPnl[s]>=0) ? "PROFIT" : "LOSS";
      Print("  ", sigNames[s], " | Trades=", sigCounts[s], " | WR=", DoubleToString(wr,0), "% | PnL=$", DoubleToString(sigPnl[s],2), " | Avg=$", DoubleToString(sigPnl[s]/sigCounts[s],2), " [", tag, "]");
   }
   Print("");
   Print("--- MONTHLY ---");
   int profM=0;
   for(int m=0; m<numM; m++)
   {
      string sign = (mPnl[m]>=0) ? "+" : "-";
      if(mPnl[m]>=0) profM++;
      Print("  ", mKeys[m], ": $", DoubleToString(mPnl[m], 2), " (", mCount[m], ") ", sign);
   }
   if(numM>0) Print("  Profitable: ", profM, "/", numM, " (", DoubleToString((double)profM/numM*100,0), "%)");

   // Diagnostic: hours
   Print("");
   Print("--- DIAGNOSTIC ---");
   Print("  Win rate by hour:");
   int hW[24], hT[24]; ArrayInitialize(hW,0); ArrayInitialize(hT,0);
   for(int i2=0; i2<totalDeals; i2++)
   {
      ulong tk2=HistoryDealGetTicket(i2);
      if(HistoryDealGetString(tk2,DEAL_SYMBOL)!=_Symbol) continue;
      if(HistoryDealGetInteger(tk2,DEAL_MAGIC)!=magicNumber) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(tk2,DEAL_ENTRY)!=DEAL_ENTRY_IN) continue;
      MqlDateTime dt2; TimeToStruct((datetime)HistoryDealGetInteger(tk2,DEAL_TIME),dt2);
      ulong pid=HistoryDealGetInteger(tk2,DEAL_POSITION_ID);
      for(int j2=0; j2<totalDeals; j2++)
      { ulong t2=HistoryDealGetTicket(j2); if(HistoryDealGetInteger(t2,DEAL_POSITION_ID)==pid && (ENUM_DEAL_ENTRY)HistoryDealGetInteger(t2,DEAL_ENTRY)==DEAL_ENTRY_OUT) { hT[dt2.hour]++; if(HistoryDealGetDouble(t2,DEAL_PROFIT)>0) hW[dt2.hour]++; break; } }
   }
   for(int h=0; h<24; h++)
   {
      if(hT[h]>3)
      { double wr2=(double)hW[h]/hT[h]*100; string mk=""; if(wr2<35)mk=" <<< BAD"; else if(wr2>60)mk=" <<< GOOD"; Print("    ",(h<10?"0":""),h,":00 = ",DoubleToString(wr2,1),"% (",hT[h],")",mk); }
   }

   Print("  Win rate by day:");
   string dN[]={"Dim","Lun","Mar","Mer","Jeu","Ven","Sam"};
   int dW[7],dT[7]; ArrayInitialize(dW,0); ArrayInitialize(dT,0);
   for(int i3=0; i3<totalDeals; i3++)
   {
      ulong tk3=HistoryDealGetTicket(i3);
      if(HistoryDealGetString(tk3,DEAL_SYMBOL)!=_Symbol) continue;
      if(HistoryDealGetInteger(tk3,DEAL_MAGIC)!=magicNumber) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(tk3,DEAL_ENTRY)!=DEAL_ENTRY_IN) continue;
      MqlDateTime dt3; TimeToStruct((datetime)HistoryDealGetInteger(tk3,DEAL_TIME),dt3);
      ulong pid2=HistoryDealGetInteger(tk3,DEAL_POSITION_ID);
      for(int j3=0; j3<totalDeals; j3++)
      { ulong t3=HistoryDealGetTicket(j3); if(HistoryDealGetInteger(t3,DEAL_POSITION_ID)==pid2 && (ENUM_DEAL_ENTRY)HistoryDealGetInteger(t3,DEAL_ENTRY)==DEAL_ENTRY_OUT) { dT[dt3.day_of_week]++; if(HistoryDealGetDouble(t3,DEAL_PROFIT)>0) dW[dt3.day_of_week]++; break; } }
   }
   for(int dd=0; dd<7; dd++)
   {
      if(dT[dd]>3)
      { double wr3=(double)dW[dd]/dT[dd]*100; string mk2=""; if(wr3<35)mk2=" <<< BAD"; else if(wr3>60)mk2=" <<< GOOD"; Print("    ",dN[dd]," = ",DoubleToString(wr3,1),"% (",dT[dd],")",mk2); }
   }

   Print("");
   Print("--- SETTINGS ---");
   Print("  Lot: ", InpLotSize);
   Print("  SELL: SL=", InpSL_Sell, "x TP=", InpTP_Sell, "x ATR");
   Print("  BUY:  SL=", InpSL_Buy, "x TP=", InpTP_Buy, "x ATR");
   Print("  MinSup=", InpMinSupStr, " MinRes=", InpMinResStr);
   Print("  RSI OB=", InpRSIOverbought, " OS=", InpRSIOversold);

   Print("");
   Print("======================================================================");
   Print("  Copy everything above and send for analysis");
   Print("======================================================================");
}

//+------------------------------------------------------------------+
double OnTester() { return 0; }
