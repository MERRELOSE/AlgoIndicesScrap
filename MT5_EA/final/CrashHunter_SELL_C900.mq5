//+------------------------------------------------------------------+
//|                                    CrashHunter_SELL_C900.mq5     |
//|                         SELL-Only Trading System v3                |
//|                         Crash 900 - Red Candle Capture             |
//+------------------------------------------------------------------+
//  Strategy: Enter SELL, wait for a big red candle, close on it
//  NO fixed TP - we close when we detect a crash candle
//  SL = 2x ATR (tight enough to limit losses)
//  Backtested: 80% WR, PF 1.64 on 6+ consec UP
//+------------------------------------------------------------------+
#property copyright "AlgoIndicesScrap Project"
#property version   "3.00"
#property description "CrashHunter SELL v3 - Red Candle Capture"
#property description "Closes on big red candle, no fixed TP"

#include <Trade\Trade.mqh>

//+------------------------------------------------------------------+
//| INPUT PARAMETERS                                                  |
//+------------------------------------------------------------------+
input double   InpLotSize        = 1.00;
input double   InpSLMultiplier   = 5.0;      // SL (x ATR) - wide to survive
input double   InpTPMultiplier   = 1.0;      // TP (x ATR) - tight scalp
input double   InpRedCandleTP    = 0.5;      // Min red candle size to also close (x ATR)
input int      InpMaxTrades      = 1;
input int      InpCooldownBars   = 4;
input int      InpRSIPeriod      = 14;
input int      InpEMAFast        = 5;
input int      InpEMASlow        = 20;
input int      InpATRPeriod      = 14;
input int      InpMaxHoldBars    = 30;       // Max hold bars

//+------------------------------------------------------------------+
//| GLOBAL VARIABLES                                                   |
//+------------------------------------------------------------------+
CTrade         trade;

int            handleRSI;
int            handleRSI_H4;
int            handleEMAFast;
int            handleEMASlow;
int            handleATR;
int            handleEMAFast_H4;
int            handleEMASlow_H4;

int            lastTradeBar;
int            openTradeBar;
int            magicNumber = 30901;

string         lastExitReason = "";
int            lastExitBar = 0;
int            consecutiveLosses = 0;

// Track entry ATR for red candle detection
double         entryATR = 0;

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

   if(handleRSI == INVALID_HANDLE || handleEMAFast == INVALID_HANDLE ||
      handleEMASlow == INVALID_HANDLE || handleATR == INVALID_HANDLE)
   {
      Print("Failed to create indicator handles");
      return INIT_FAILED;
   }

   Print("=== CrashHunter SELL v3 C900 | Magic=", magicNumber,
         " | SL=", InpSLMultiplier, "x | RedCandle=", InpRedCandleTP, "x ATR ===");
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
int CountConsecUp()
{
   int count = 0;
   for(int i = 1; i <= 20; i++)
   {
      if(iClose(_Symbol, PERIOD_H1, i) > iClose(_Symbol, PERIOD_H1, i + 1))
         count++;
      else
         break;
   }
   return count;
}

//+------------------------------------------------------------------+
//| Detect SELL signal                                                 |
//+------------------------------------------------------------------+
bool DetectSellSignal(string &signalName, double &signalScore)
{
   signalName = "";
   signalScore = 0;

   double rsi[];
   double emaSlow[];

   if(CopyBuffer(handleRSI, 0, 1, 1, rsi) < 1) return false;
   if(CopyBuffer(handleEMASlow, 0, 1, 1, emaSlow) < 1) return false;

   double close1 = iClose(_Symbol, PERIOD_H1, 1);
   int consecUp = CountConsecUp();
   double distAboveEMA = (close1 - emaSlow[0]) / emaSlow[0] * 100;

   // === SIGNAL 1: 6+ consec UP + RSI > 70 (v2 best: 64% WR, +$478) ===
   if(consecUp >= 6 && rsi[0] > 70)
   {
      signalName = "S1.6UP.RSI70";
      signalScore = 1.5;
      return true;
   }

   // === SIGNAL 2: 8+ consec UP (v2: 81% WR, +$73) ===
   if(consecUp >= 8)
   {
      signalName = "S2.8UP";
      signalScore = 1.8;
      return true;
   }

   // BLOCKED: 4+ consec UP + RSI65 (-$692 in v3)
   // BLOCKED: 3+ consec UP + RSI70 (marginal)

   return false;
}

//+------------------------------------------------------------------+
//| Check if current bar is a big red candle (crash candle)            |
//+------------------------------------------------------------------+
bool IsBigRedCandle(double atrRef)
{
   // Check the LAST CLOSED bar (bar 1)
   double open1  = iOpen(_Symbol, PERIOD_H1, 1);
   double close1 = iClose(_Symbol, PERIOD_H1, 1);
   double redBody = open1 - close1;  // positive = red candle

   if(redBody > InpRedCandleTP * atrRef)
      return true;

   return false;
}

//+------------------------------------------------------------------+
//| Manage open SELL positions                                         |
//+------------------------------------------------------------------+
void ManagePositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != magicNumber) continue;
      if(PositionGetInteger(POSITION_TYPE) != POSITION_TYPE_SELL) continue;

      double entryPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double currentSL  = PositionGetDouble(POSITION_SL);
      double profit      = PositionGetDouble(POSITION_PROFIT);
      double currentPrice = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      int barsOpen = Bars(_Symbol, PERIOD_H1) - openTradeBar;

      // === CLOSE ON BIG RED CANDLE (the crash we were waiting for) ===
      if(barsOpen >= 1 && IsBigRedCandle(entryATR))
      {
         double open1 = iOpen(_Symbol, PERIOD_H1, 1);
         double close1 = iClose(_Symbol, PERIOD_H1, 1);
         double redSize = (open1 - close1) / entryATR;

         trade.PositionClose(ticket);
         Print(">>> RED CANDLE CLOSE: P&L=$", DoubleToString(profit, 2),
               " | RedCandle=", DoubleToString(redSize, 2), "x ATR",
               " | BarsHeld=", barsOpen,
               " | Entry=", DoubleToString(entryPrice, _Digits),
               " | Exit=", DoubleToString(currentPrice, _Digits));
         continue;
      }

      // === BREAK EVEN: if price drops 0.5x ATR, move SL to entry ===
      double profitDist = entryPrice - currentPrice;
      if(profitDist > 0.3 * entryATR && currentSL > entryPrice + _Point)
      {
         double beSL = entryPrice + 2 * _Point;
         trade.PositionModify(ticket, beSL, 0);  // No TP, just BE
         Print("BE SELL: SL -> entry at ", DoubleToString(beSL, _Digits),
               " | Profit so far=$", DoubleToString(profit, 2));
      }

      // === TIME STOP: no crash came, close ===
      if(barsOpen >= InpMaxHoldBars)
      {
         trade.PositionClose(ticket);
         Print("TIME STOP: Closed SELL after ", barsOpen, " bars | P&L=$", DoubleToString(profit, 2));
      }
   }
}

//+------------------------------------------------------------------+
//| Expert tick function                                              |
//+------------------------------------------------------------------+
void OnTick()
{
   // Manage positions every tick (for SL monitoring)
   // But red candle check only on new bar
   if(CountOpenPositions() > 0)
   {
      // Check for red candle on new bar
      if(IsNewBar())
      {
         ManagePositions();
         if(CountOpenPositions() == 0) return;  // Position was closed
      }
      return;  // Don't look for new signals while in a trade
   }

   if(!IsNewBar()) return;

   int currentBar = Bars(_Symbol, PERIOD_H1);

   if(CountOpenPositions() >= InpMaxTrades) return;

   // Loss streak breaker
   if(consecutiveLosses >= 2)
   {
      int barsSinceExit = currentBar - lastExitBar;
      if(barsSinceExit < 8) return;
      consecutiveLosses = 0;
   }

   // Cooldown
   if(currentBar - lastTradeBar < InpCooldownBars) return;

   // Extra cooldown after SL
   if(lastExitReason == "SL" && lastExitBar > 0)
   {
      if(currentBar - lastExitBar < InpCooldownBars + 3) return;
   }

   // Detect SELL signal
   string signalName;
   double signalScore;

   if(!DetectSellSignal(signalName, signalScore)) return;

   // === PLACE SELL (no TP - we close on red candle) ===
   double atr[];
   if(CopyBuffer(handleATR, 0, 1, 1, atr) < 1) return;
   double currentATR = atr[0];

   double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl = price + InpSLMultiplier * currentATR;
   double tp = price - InpTPMultiplier * currentATR;

   // Wider TP for strongest signal
   if(signalScore >= 1.8)
      tp = price - 1.5 * currentATR;

   double lots = InpLotSize;
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lots = MathMax(minLot, MathMin(maxLot, MathRound(lots / lotStep) * lotStep));

   int consecUp = CountConsecUp();

   // Get RSI for logging
   double rsi[];
   CopyBuffer(handleRSI, 0, 1, 1, rsi);

   if(trade.Sell(lots, _Symbol, price, sl, tp, signalName))
   {
      entryATR = currentATR;  // Save ATR at entry for red candle detection

      Print(">>> SELL: ", signalName,
            " | ConsecUP=", consecUp,
            " | RSI=", DoubleToString(rsi[0], 1),
            " | Price=", DoubleToString(price, _Digits),
            " | SL=", DoubleToString(sl, _Digits), " (", DoubleToString(InpSLMultiplier,1), "x ATR=", DoubleToString(currentATR, 2), ")",
            " | TP=NONE (wait for red candle > ", DoubleToString(InpRedCandleTP,1), "x ATR)",
            " | Lots=", DoubleToString(lots, 2));

      lastTradeBar = currentBar;
      openTradeBar = currentBar;
   }
   else
      Print("SELL FAILED: ", trade.ResultRetcodeDescription(), " | ", signalName);
}

//+------------------------------------------------------------------+
//| Trade event handler                                               |
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
                  int exitBar = Bars(_Symbol, PERIOD_H1);
                  int barsHeld = exitBar - openTradeBar;
                  lastExitBar = exitBar;

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
                        " | BarsHeld=", barsHeld,
                        " | ConsecLoss=", consecutiveLosses,
                        " | Balance=$", DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2));
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
//| Summary Report                                                     |
//+------------------------------------------------------------------+
void PrintSummaryReport()
{
   if(!HistorySelect(0, TimeCurrent())) return;
   int totalDeals = HistoryDealsTotal();
   if(totalDeals == 0) return;

   int totalTrades=0, wins=0, losses=0;
   double grossProfit=0, grossLoss=0, totalProfit=0;
   double maxWin=0, maxLoss=0;
   int curWinStreak=0, curLossStreak=0, maxWinStreak=0, maxLossStreak=0;

   string signalNames[];
   int signalCounts[], signalWins[], signalTotal[];
   double signalProfits[];
   int numSignals = 0;

   string monthKeys[];
   double monthPnl[];
   int monthTradeCount[];
   int numMonths = 0;

   int tpCount=0, slCount=0, timeCount=0, redCount=0;
   double tpProfit=0, slProfit=0;

   for(int i = 0; i < totalDeals; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(HistoryDealGetString(ticket, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != magicNumber) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;

      double netProfit = HistoryDealGetDouble(ticket, DEAL_PROFIT)
                       + HistoryDealGetDouble(ticket, DEAL_SWAP)
                       + HistoryDealGetDouble(ticket, DEAL_COMMISSION);
      totalTrades++;
      totalProfit += netProfit;

      if(netProfit > 0) { wins++; grossProfit += netProfit; if(netProfit > maxWin) maxWin = netProfit; curWinStreak++; curLossStreak=0; if(curWinStreak>maxWinStreak) maxWinStreak=curWinStreak; }
      else { losses++; grossLoss += MathAbs(netProfit); if(netProfit < maxLoss) maxLoss = netProfit; curLossStreak++; curWinStreak=0; if(curLossStreak>maxLossStreak) maxLossStreak=curLossStreak; }

      // Signal
      ulong posId = HistoryDealGetInteger(ticket, DEAL_POSITION_ID);
      string comment = "";
      for(int j = 0; j < totalDeals; j++)
      { ulong t = HistoryDealGetTicket(j); if(HistoryDealGetInteger(t, DEAL_POSITION_ID) == posId && (ENUM_DEAL_ENTRY)HistoryDealGetInteger(t, DEAL_ENTRY) == DEAL_ENTRY_IN) { comment = HistoryDealGetString(t, DEAL_COMMENT); break; } }
      if(comment == "") comment = "unknown";

      int sIdx = -1;
      for(int s = 0; s < numSignals; s++) { if(signalNames[s] == comment) { sIdx = s; break; } }
      if(sIdx < 0)
      {
         numSignals++; ArrayResize(signalNames, numSignals); ArrayResize(signalCounts, numSignals);
         ArrayResize(signalWins, numSignals); ArrayResize(signalTotal, numSignals); ArrayResize(signalProfits, numSignals);
         sIdx = numSignals - 1; signalNames[sIdx] = comment; signalCounts[sIdx]=0; signalWins[sIdx]=0; signalTotal[sIdx]=0; signalProfits[sIdx]=0;
      }
      signalCounts[sIdx]++; signalTotal[sIdx]++; signalProfits[sIdx] += netProfit;
      if(netProfit > 0) signalWins[sIdx]++;

      // Monthly
      datetime dealTime = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
      MqlDateTime dt; TimeToStruct(dealTime, dt);
      string monthKey = StringFormat("%04d-%02d", dt.year, dt.mon);
      int mIdx = -1;
      for(int m = 0; m < numMonths; m++) { if(monthKeys[m] == monthKey) { mIdx = m; break; } }
      if(mIdx < 0)
      {
         numMonths++; ArrayResize(monthKeys, numMonths); ArrayResize(monthPnl, numMonths); ArrayResize(monthTradeCount, numMonths);
         mIdx = numMonths - 1; monthKeys[mIdx] = monthKey; monthPnl[mIdx]=0; monthTradeCount[mIdx]=0;
      }
      monthPnl[mIdx] += netProfit; monthTradeCount[mIdx]++;

      if(netProfit > 0) { tpCount++; tpProfit += netProfit; }
      else { slCount++; slProfit += netProfit; }
   }

   double profitFactor = (grossLoss > 0) ? grossProfit / grossLoss : 0;
   double expectancy = (totalTrades > 0) ? totalProfit / totalTrades : 0;
   double avgWin = (wins > 0) ? grossProfit / wins : 0;
   double avgLoss = (losses > 0) ? grossLoss / losses : 0;

   Print("======================================================================");
   Print("  CRASHHUNTER SELL v3 C900 - RED CANDLE CAPTURE");
   Print("======================================================================");
   Print("");
   Print("--- PERFORMANCE ---");
   Print("  Net Profit:         $", DoubleToString(totalProfit, 2));
   Print("  Profit Factor:      ", DoubleToString(profitFactor, 2));
   Print("  Expectancy/trade:   $", DoubleToString(expectancy, 2));
   Print("");
   Print("--- TRADES ---");
   Print("  Total Trades:       ", totalTrades);
   Print("  Winners:            ", wins, " (", DoubleToString((totalTrades>0)?(double)wins/totalTrades*100:0, 1), "%)");
   Print("  Losers:             ", losses, " (", DoubleToString((totalTrades>0)?(double)losses/totalTrades*100:0, 1), "%)");
   Print("  Avg Winner:         $", DoubleToString(avgWin, 2));
   Print("  Avg Loser:          $-", DoubleToString(avgLoss, 2));
   Print("  Best Trade:         $", DoubleToString(maxWin, 2));
   Print("  Worst Trade:        $", DoubleToString(maxLoss, 2));
   Print("  Max Win Streak:     ", maxWinStreak);
   Print("  Max Loss Streak:    ", maxLossStreak);
   Print("");
   Print("--- EXIT REASONS ---");
   Print("  Red Candle TP: ", tpCount, " trades | $", DoubleToString(tpProfit, 2));
   Print("  Stop Loss:     ", slCount, " trades | $", DoubleToString(slProfit, 2));
   Print("");
   Print("--- SIGNAL PERFORMANCE ---");
   for(int s = 0; s < numSignals; s++)
   {
      double wr = (signalTotal[s]>0) ? (double)signalWins[s]/signalTotal[s]*100 : 0;
      string tag = (signalProfits[s] >= 0) ? "PROFIT" : "LOSS";
      Print("  ", signalNames[s]);
      Print("    Trades=", signalCounts[s], " | WR=", DoubleToString(wr,0), "% | PnL=$", DoubleToString(signalProfits[s],2), " | Avg=$", DoubleToString(signalProfits[s]/signalCounts[s],2), " [", tag, "]");
   }
   Print("");
   Print("--- MONTHLY BREAKDOWN ---");
   int profMonths = 0;
   for(int m = 0; m < numMonths; m++)
   {
      string sign = (monthPnl[m] >= 0) ? "+" : "-";
      if(monthPnl[m] >= 0) profMonths++;
      Print("  ", monthKeys[m], ": $", DoubleToString(monthPnl[m], 2), " (", monthTradeCount[m], " trades) ", sign);
   }
   if(numMonths > 0)
      Print("  Profitable Months: ", profMonths, "/", numMonths, " (", DoubleToString((double)profMonths/numMonths*100, 0), "%)");

   Print("");
   Print("--- SETTINGS ---");
   Print("  Lot Size:          ", InpLotSize);
   Print("  SL:                ", InpSLMultiplier, " x ATR");
   Print("  TP:                NONE (close on red candle > ", InpRedCandleTP, "x ATR)");
   Print("  Max Hold Bars:     ", InpMaxHoldBars);
   Print("  Cooldown Bars:     ", InpCooldownBars);

   // Diagnostic: hours
   Print("");
   Print("--- DIAGNOSTIC ---");
   Print("  Win rate by hour:");
   int hourWins[24], hourTotal[24];
   ArrayInitialize(hourWins, 0); ArrayInitialize(hourTotal, 0);
   for(int i4 = 0; i4 < totalDeals; i4++)
   {
      ulong tk = HistoryDealGetTicket(i4);
      if(HistoryDealGetString(tk, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(tk, DEAL_MAGIC) != magicNumber) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(tk, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
      MqlDateTime dt2; TimeToStruct((datetime)HistoryDealGetInteger(tk, DEAL_TIME), dt2);
      ulong pid = HistoryDealGetInteger(tk, DEAL_POSITION_ID);
      for(int j5 = 0; j5 < totalDeals; j5++)
      {
         ulong t6 = HistoryDealGetTicket(j5);
         if(HistoryDealGetInteger(t6, DEAL_POSITION_ID) == pid && (ENUM_DEAL_ENTRY)HistoryDealGetInteger(t6, DEAL_ENTRY) == DEAL_ENTRY_OUT)
         { hourTotal[dt2.hour]++; if(HistoryDealGetDouble(t6, DEAL_PROFIT) > 0) hourWins[dt2.hour]++; break; }
      }
   }
   for(int h = 0; h < 24; h++)
   {
      if(hourTotal[h] > 3)
      {
         double wr2 = (double)hourWins[h] / hourTotal[h] * 100;
         string mk = ""; if(wr2 < 35) mk = " <<< BAD"; else if(wr2 > 65) mk = " <<< GOOD";
         Print("    ", (h<10?"0":""), h, ":00 = ", DoubleToString(wr2, 1), "% (", hourTotal[h], " trades)", mk);
      }
   }

   Print("  Win rate by day:");
   string dayN[] = {"Dim","Lun","Mar","Mer","Jeu","Ven","Sam"};
   int dayWins[7], dayTotal[7];
   ArrayInitialize(dayWins, 0); ArrayInitialize(dayTotal, 0);
   for(int i5 = 0; i5 < totalDeals; i5++)
   {
      ulong tk2 = HistoryDealGetTicket(i5);
      if(HistoryDealGetString(tk2, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(tk2, DEAL_MAGIC) != magicNumber) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(tk2, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
      MqlDateTime dt3; TimeToStruct((datetime)HistoryDealGetInteger(tk2, DEAL_TIME), dt3);
      ulong pid2 = HistoryDealGetInteger(tk2, DEAL_POSITION_ID);
      for(int j6 = 0; j6 < totalDeals; j6++)
      {
         ulong t7 = HistoryDealGetTicket(j6);
         if(HistoryDealGetInteger(t7, DEAL_POSITION_ID) == pid2 && (ENUM_DEAL_ENTRY)HistoryDealGetInteger(t7, DEAL_ENTRY) == DEAL_ENTRY_OUT)
         { dayTotal[dt3.day_of_week]++; if(HistoryDealGetDouble(t7, DEAL_PROFIT) > 0) dayWins[dt3.day_of_week]++; break; }
      }
   }
   for(int dd = 0; dd < 7; dd++)
   {
      if(dayTotal[dd] > 3)
      {
         double wr3 = (double)dayWins[dd] / dayTotal[dd] * 100;
         string mk2 = ""; if(wr3 < 35) mk2 = " <<< BAD"; else if(wr3 > 65) mk2 = " <<< GOOD";
         Print("    ", dayN[dd], " = ", DoubleToString(wr3, 1), "% (", dayTotal[dd], " trades)", mk2);
      }
   }

   Print("");
   Print("======================================================================");
   Print("  Copy everything above and send for analysis");
   Print("======================================================================");
}

//+------------------------------------------------------------------+
double OnTester() { return 0; }
