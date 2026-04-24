//+------------------------------------------------------------------+
//|                                CrashHunter_v5_C900_Licensed.mq5  |
//|                         Behavior-Based Trading System             |
//|                         Licensed version with subscription mgmt   |
//+------------------------------------------------------------------+
#property copyright "AlgoIndicesScrap"
#property link      ""
#property version   "5.90"
#property description "CrashHunter - Crash Index Trading System"
#property description "Licensed product. Unauthorized distribution prohibited."

#include <Trade\Trade.mqh>
#include "license\LicenseManager.mqh"

//+------------------------------------------------------------------+
//| INPUT PARAMETERS                                                  |
//+------------------------------------------------------------------+

// --- LICENSE (provided by admin) ---
input string   InpLicenseKey     = "";       // License Key (XXXX-XXXX-XXXX-XXXX)
input long     InpLicenseAccount = 0;        // Licensed Account Number
input string   InpLicenseExpiry  = "";       // License Expiry (YYYY.MM.DD)

// --- Risk Management ---
input double   InpLotSize        = 1.00;     // Lot size
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

// === TP CONTINUATION TRACKING ===
// After a trade hits TP, we track how far price continues
struct TPTrack
{
   double   entryPrice;
   double   tpPrice;
   double   atrAtEntry;
   datetime tpHitTime;
   double   maxPriceAfterTP;
   int      barsTracked;
   bool     active;
};

TPTrack  tpTracks[];        // Array of TP continuations to track
int      tpTrackCount = 0;
int      TP_TRACK_BARS = 30; // Track 30 bars after TP

// Aggregated stats
int      totalTPHits = 0;
double   sumContinuationATR = 0;   // sum of (maxAfterTP - tpPrice) / ATR
int      countReached4x = 0;
int      countReached5x = 0;
int      countReached6x = 0;
int      countReached8x = 0;
int      countReached10x = 0;
double   allContinuations[];       // store each continuation in ATR for percentiles

//+------------------------------------------------------------------+
//| Expert initialization                                             |
//+------------------------------------------------------------------+
// Global license status
LICENSE_STATUS g_licenseStatus = LICENSE_NOT_SET;

int OnInit()
{
   // ============================================
   // LICENSE CHECK - Must pass before anything
   // ============================================
   g_licenseStatus = ValidateLicense(InpLicenseKey, InpLicenseAccount, InpLicenseExpiry);

   int daysLeft = DaysRemaining(InpLicenseExpiry);
   ShowLicenseStatus(g_licenseStatus, InpLicenseExpiry, daysLeft);

   if(g_licenseStatus != LICENSE_VALID)
   {
      switch(g_licenseStatus)
      {
         case LICENSE_NOT_SET:
            Print("LICENSE: No license key entered. EA disabled.");
            Print("LICENSE: Enter your License Key, Account Number, and Expiry Date in settings.");
            Alert("CrashHunter - Please enter your license key in EA settings");
            break;
         case LICENSE_EXPIRED:
            Print("LICENSE: Subscription expired on ", InpLicenseExpiry);
            Print("LICENSE: Contact admin to renew.");
            Alert("CrashHunter - Your license expired on ", InpLicenseExpiry, ". Contact admin to renew.");
            break;
         case LICENSE_WRONG_ACCOUNT:
            Print("LICENSE: This license is for account ", InpLicenseAccount,
                  " but you are on account ", AccountInfoInteger(ACCOUNT_LOGIN));
            Alert("CrashHunter - License not valid for this account");
            break;
         case LICENSE_INVALID_KEY:
            Print("LICENSE: Invalid license key");
            Alert("CrashHunter - Invalid license key. Check your key and try again.");
            break;
      }
      // Still allow init so chart shows error message, but EA won't trade
      // DON'T return INIT_FAILED - that removes the EA from chart
   }
   else
   {
      Print("LICENSE: Valid | Account: ", InpLicenseAccount,
            " | Expires: ", InpLicenseExpiry, " (", daysLeft, " days)");
   }

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

   Print("CrashHunter v5 C900 Licensed | Symbol: ", _Symbol);

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
//| Count consecutive UP candles (C900 specific)                      |
//+------------------------------------------------------------------+
int CountConsecUp()
{
   int count = 0;
   for(int i = 1; i <= 10; i++)
   {
      double close_i = iClose(_Symbol, PERIOD_H1, i);
      double close_prev = iClose(_Symbol, PERIOD_H1, i + 1);
      if(close_i > close_prev)
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

   // v5: Vol squeeze is NO LONGER a filter - it's now a signal!
   // (Squeeze+uptrend = 66% in 2026, our strongest signal)

   // H4 trend filter
   int h4Trend = GetH4Trend();
   if(h4Trend == -1)
   {
      signalName = "FILTER:h4_bearish";
      return false;
   }

   // === v5 SIGNALS - RECALIBRATED FOR 2026 MARKET REALITY ===
   //
   // 2026 signal reliability (tested on real 2026 data):
   //   Squeeze+uptrend       66% --> NEW KING SIGNAL
   //   RSI 70-80 continue    61% --> NEW (momentum continuation)
   //   RSI 20-35 bounce      53% --> still OK
   //   Consec down 3+        51% --> marginal, needs confluence
   //   Bullish EMA cross     45% --> DEMOTED (was 56% in 2025, now losing)
   //   Post-crash recovery   35% --> DEMOTED (was 57% in 2025, now weak)
   //   RSI <20 deep oversold 44% --> BLOCKED (trap in 2026)
   //
   // v5 changes:
   //   - post_crash: no longer standalone, needs confluence
   //   - bullish_cross: demoted, lower score
   //   - NEW: squeeze_in_uptrend (66% in 2026!)
   //   - NEW: rsi_momentum (RSI 70-80 continuation, 61%)
   //   - RSI <20 deep oversold now BLOCKED entirely

   signalName = "";
   signalScore = 0;
   int signalCount = 0;
   bool hasStrongSignal = false;

   // Detect conditions
   bool hasPostCrash = DetectCrashSpike(InpSpikeLookback);
   bool hasRSIOS = (currentRSI >= 25 && currentRSI < InpRSIOversold);  // v5: raised floor from 20 to 25
   bool hasRSIMomentum = (currentRSI >= 70 && currentRSI < 80);        // v5: NEW
   int consecDown = CountConsecDown();
   bool hasConsecRev = (consecDown >= InpConsecDown && currentRSI > 25);
   bool hasOverext = (distEMA20 < -1.0 && distEMA20 > -3.0);
   bool hasBullCross = (currentEMAFast > currentEMASlow && prevEMAFast <= prevEMASlow);
   bool hasH4Bull = (h4Trend == 1);

   // v5 NEW: Volatility squeeze + uptrend detection (66% in 2026!)
   bool hasSqueeze = (volRatio < 0.6);
   bool hasUptrend = (currentEMAFast > currentEMASlow);
   bool hasSqueezeUptrend = (hasSqueeze && hasUptrend);

   // === HARD FILTERS ===

   // Doji filter (validated 8/8 years, -23% edge)
   if(IsDoji(1))
   {
      signalName = "FILTER:doji";
      return false;
   }

   // v5: Deep oversold RSI < 25 alone = TRAP in 2026 (44%)
   if(currentRSI < 25 && !hasPostCrash && !hasOverext)
   {
      signalName = "FILTER:deep_oversold_trap";
      return false;
   }

   // H4 bearish filter
   if(h4Trend == -1)
   {
      signalName = "FILTER:h4_bearish";
      return false;
   }

   // === v5.1 BLOCKS: Remove losing combos from backtest ===

   // BLOCK: rsi_os+overext+h4 (13% WR, -$59) - the recurring trap
   if(hasRSIOS && hasOverext && hasH4Bull && !hasPostCrash && !hasConsecRev && !hasSqueeze)
   {
      signalName = "BLOCK:rsi_overext_h4";
      return false;
   }

   // BLOCK: squeeze_up+cross WITHOUT h4 (39% WR, -$31)
   // squeeze_up+cross+h4 is profitable (+$37), so only block when no H4
   if(hasSqueezeUptrend && hasBullCross && !hasH4Bull && !hasRSIOS && !hasConsecRev)
   {
      signalName = "BLOCK:squeeze_cross_no_h4";
      return false;
   }

   // BLOCK: rsi_momentum WITHOUT h4 (0% WR, -$21)
   // rsi_momentum+h4 is profitable (+$252), so only block when no H4
   if(hasRSIMomentum && !hasH4Bull && !hasSqueezeUptrend)
   {
      signalName = "BLOCK:momentum_no_h4";
      return false;
   }

   // BLOCK: squeeze_up+rsi_momentum WITHOUT h4 (33% WR, -$13)
   if(hasSqueezeUptrend && hasRSIMomentum && !hasH4Bull)
   {
      signalName = "BLOCK:squeeze_momentum_no_h4";
      return false;
   }

   // BLOCK: rsi_os+consec_rev+post_crash+h4 (33% WR, -$11)
   if(hasRSIOS && hasConsecRev && hasPostCrash && hasH4Bull && !hasOverext)
   {
      signalName = "BLOCK:rsi_consec_crash_h4";
      return false;
   }

   // ================================================================
   // C900 SPECIFIC BLOCKS (from Crash 900 backtest with v5)
   // These lose on C900 but may profit on C1000
   // ================================================================

   // C900 BLOCK: squeeze_up+rsi_momentum+h4 (25% WR, -$336 BIGGEST LOSER)
   // On C1000 also loses -$46, so safe to block
   if(hasSqueezeUptrend && hasRSIMomentum && hasH4Bull)
   {
      signalName = "BLOCK_C900:squeeze_momentum_h4";
      return false;
   }

   // C900 BLOCK: squeeze_up+cross+h4 (26% WR, -$201)
   // On C1000 also loses -$58
   if(hasSqueezeUptrend && hasBullCross && hasH4Bull && !hasRSIOS && !hasConsecRev)
   {
      signalName = "BLOCK_C900:squeeze_cross_h4";
      return false;
   }

   // C900 BLOCK: rsi_os+consec_rev+overext+h4 (23% WR, -$169)
   // On C1000 this PROFITS (+$139), but on C900 it's a trap
   if(hasRSIOS && hasConsecRev && hasOverext && hasH4Bull && !hasPostCrash)
   {
      signalName = "BLOCK_C900:rsi_consec_overext_h4";
      return false;
   }

   // C900 BLOCK: rsi_os+overext+post_crash WITHOUT h4 (0% WR, -$90)
   // On C1000 this profits (+$44), but on C900 crashes are more violent
   if(hasRSIOS && hasOverext && hasPostCrash && !hasH4Bull && !hasConsecRev)
   {
      signalName = "BLOCK_C900:rsi_overext_crash_no_h4";
      return false;
   }

   // C900 BLOCK: squeeze_up+consec_rev WITHOUT h4 (33% WR, -$54)
   if(hasSqueezeUptrend && hasConsecRev && !hasH4Bull && !hasRSIOS)
   {
      signalName = "BLOCK_C900:squeeze_consec_no_h4";
      return false;
   }

   // C900 FILTER: 6+ consecutive UP candles = reversal coming (-12% to -21% edge)
   // Validated by behavior discovery on C900 data
   int consecUp = CountConsecUp();
   if(consecUp >= 6)
   {
      signalName = "FILTER_C900:consec_up_reversal";
      return false;
   }

   // === BUILD SIGNALS (ordered by 2026 reliability) ===

   // SIGNAL 1 - NEW: Squeeze + Uptrend (66% in 2026 = strongest signal)
   if(hasSqueezeUptrend)
   {
      signalName += "squeeze_up+";
      signalScore += 1.0;
      signalCount++;
      hasStrongSignal = true;  // Can enter alone (66%!)
   }

   // SIGNAL 2 - NEW: RSI Momentum 70-80 (61% in 2026)
   if(hasRSIMomentum && hasUptrend)
   {
      signalName += "rsi_momentum+";
      signalScore += 0.8;
      signalCount++;
   }

   // SIGNAL 3: RSI oversold 25-35 bounce (53% in 2026, stable across years)
   if(hasRSIOS)
   {
      signalName += "rsi_os+";
      signalScore += 0.5;
      signalCount++;
   }

   // SIGNAL 4: Consecutive down reversal (51%, needs confluence)
   if(hasConsecRev)
   {
      signalName += "consec_rev+";
      signalScore += 0.3;
      signalCount++;
   }

   // SIGNAL 5: Overextended below EMA20 (moderate)
   if(hasOverext)
   {
      signalName += "overext+";
      signalScore += 0.3;
      signalCount++;
   }

   // SIGNAL 6: Post-crash recovery (DEMOTED: 35% in 2026, needs confluence)
   // v5: No longer standalone, must combine with RSI or overext
   if(hasPostCrash && (hasRSIOS || hasOverext))
   {
      signalName += "post_crash+";
      signalScore += 0.4;
      signalCount++;
   }

   // SIGNAL 7: Bullish EMA cross (DEMOTED: 45% in 2026, only as bonus)
   if(hasBullCross && signalCount > 0)
   {
      signalName += "cross+";
      signalScore += 0.2;
   }

   // H4 bullish confirmation bonus
   if(hasH4Bull && signalCount > 0)
   {
      signalName += "h4+";
      signalScore += 0.3;
   }

   // Remove trailing +
   if(StringLen(signalName) > 0)
      signalName = StringSubstr(signalName, 0, StringLen(signalName) - 1);

   // === v5.1 ENTRY RULES ===
   // Squeeze+uptrend can enter alone (66% reliability)
   // RSI momentum needs H4 bull (0% WR without H4, 44% WR with H4)
   // Everything else needs 2+ signals confluence
   if(hasStrongSignal)
      return true;

   if(hasRSIMomentum && hasUptrend && hasH4Bull)
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
   // ============================================
   // LICENSE CHECK every tick
   // ============================================
   if(g_licenseStatus != LICENSE_VALID)
   {
      // Re-check in case user updated settings
      g_licenseStatus = ValidateLicense(InpLicenseKey, InpLicenseAccount, InpLicenseExpiry);
      int dl = DaysRemaining(InpLicenseExpiry);
      ShowLicenseStatus(g_licenseStatus, InpLicenseExpiry, dl);

      if(g_licenseStatus != LICENSE_VALID)
         return;  // Don't trade without valid license
   }

   // Check expiry alerts (once per day)
   int daysLeft = DaysRemaining(InpLicenseExpiry);
   CheckExpiryAlerts(daysLeft, InpLicenseExpiry);

   // Re-validate periodically (every new bar)
   static datetime lastValidation = 0;
   if(TimeCurrent() - lastValidation > 3600)  // every hour
   {
      g_licenseStatus = ValidateLicense(InpLicenseKey, InpLicenseAccount, InpLicenseExpiry);
      ShowLicenseStatus(g_licenseStatus, InpLicenseExpiry, daysLeft);
      lastValidation = TimeCurrent();

      if(g_licenseStatus != LICENSE_VALID)
         return;
   }

   // Update TP continuation tracking
   UpdateTPTracking();

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

                  // If this was a TP exit (profit > 0), start tracking continuation
                  if(dealProfit > 0)
                  {
                     double exitPrice = HistoryDealGetDouble(dealTicket, DEAL_PRICE);

                     // Find entry price from the opening deal
                     ulong posId = HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID);
                     double entryPrice = 0;
                     for(int j = 0; j < totalDeals; j++)
                     {
                        ulong t2 = HistoryDealGetTicket(j);
                        if(HistoryDealGetInteger(t2, DEAL_POSITION_ID) == posId &&
                           (ENUM_DEAL_ENTRY)HistoryDealGetInteger(t2, DEAL_ENTRY) == DEAL_ENTRY_IN)
                        {
                           entryPrice = HistoryDealGetDouble(t2, DEAL_PRICE);
                           break;
                        }
                     }

                     // Get current ATR
                     double atrBuf[];
                     double currentATR = 0;
                     if(CopyBuffer(handleATR, 0, 1, 1, atrBuf) >= 1)
                        currentATR = atrBuf[0];

                     if(entryPrice > 0 && currentATR > 0)
                     {
                        // Add to tracking array
                        tpTrackCount++;
                        ArrayResize(tpTracks, tpTrackCount);
                        tpTracks[tpTrackCount-1].entryPrice = entryPrice;
                        tpTracks[tpTrackCount-1].tpPrice = exitPrice;
                        tpTracks[tpTrackCount-1].atrAtEntry = currentATR;
                        tpTracks[tpTrackCount-1].tpHitTime = TimeCurrent();
                        tpTracks[tpTrackCount-1].maxPriceAfterTP = exitPrice;
                        tpTracks[tpTrackCount-1].barsTracked = 0;
                        tpTracks[tpTrackCount-1].active = true;
                     }
                  }
               }
            }
         }
         lastDeals = totalDeals;
      }
   }
}

//+------------------------------------------------------------------+
//| Update TP continuation tracking (called from OnTick)              |
//+------------------------------------------------------------------+
void UpdateTPTracking()
{
   if(tpTrackCount == 0) return;

   double currentHigh = iHigh(_Symbol, PERIOD_H1, 0);

   for(int i = 0; i < tpTrackCount; i++)
   {
      if(!tpTracks[i].active) continue;

      tpTracks[i].barsTracked++;

      // Update max price seen after TP
      if(currentHigh > tpTracks[i].maxPriceAfterTP)
         tpTracks[i].maxPriceAfterTP = currentHigh;

      // Stop tracking after TP_TRACK_BARS
      if(tpTracks[i].barsTracked >= TP_TRACK_BARS)
      {
         tpTracks[i].active = false;

         // Calculate continuation in ATR
         double continuation = (tpTracks[i].maxPriceAfterTP - tpTracks[i].tpPrice) / tpTracks[i].atrAtEntry;
         double totalFromEntry = (tpTracks[i].maxPriceAfterTP - tpTracks[i].entryPrice) / tpTracks[i].atrAtEntry;

         totalTPHits++;
         sumContinuationATR += continuation;

         // Check if reached higher TP levels
         double entry = tpTracks[i].entryPrice;
         double atr = tpTracks[i].atrAtEntry;
         double maxP = tpTracks[i].maxPriceAfterTP;

         if(maxP >= entry + 4.0 * atr)  countReached4x++;
         if(maxP >= entry + 5.0 * atr)  countReached5x++;
         if(maxP >= entry + 6.0 * atr)  countReached6x++;
         if(maxP >= entry + 8.0 * atr)  countReached8x++;
         if(maxP >= entry + 10.0 * atr) countReached10x++;

         // Store for percentile calculation
         int n = ArraySize(allContinuations);
         ArrayResize(allContinuations, n + 1);
         allContinuations[n] = totalFromEntry;
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
   Print("  CRASHHUNTER v5 C900 - BACKTEST SUMMARY REPORT");
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

   // === TP CONTINUATION ANALYSIS ===
   Print("");
   Print("--- TP CONTINUATION ANALYSIS (what happens AFTER TP is hit) ---");
   Print("  (Tracked ", TP_TRACK_BARS, " bars after each TP exit)");

   if(totalTPHits > 0)
   {
      double avgCont = sumContinuationATR / totalTPHits;
      Print("  TP hits tracked:    ", totalTPHits);
      Print("  Avg continuation:   ", DoubleToString(avgCont, 2), "x ATR beyond TP");
      Print("");
      Print("  After TP, price reached (from entry):");
      Print("    4.0x ATR:  ", countReached4x, " / ", totalTPHits, " (", DoubleToString((double)countReached4x/totalTPHits*100, 1), "%)");
      Print("    5.0x ATR:  ", countReached5x, " / ", totalTPHits, " (", DoubleToString((double)countReached5x/totalTPHits*100, 1), "%)");
      Print("    6.0x ATR:  ", countReached6x, " / ", totalTPHits, " (", DoubleToString((double)countReached6x/totalTPHits*100, 1), "%)");
      Print("    8.0x ATR:  ", countReached8x, " / ", totalTPHits, " (", DoubleToString((double)countReached8x/totalTPHits*100, 1), "%)");
      Print("    10.0x ATR: ", countReached10x, " / ", totalTPHits, " (", DoubleToString((double)countReached10x/totalTPHits*100, 1), "%)");

      // Sort allContinuations for percentiles
      int n = ArraySize(allContinuations);
      if(n > 0)
      {
         ArraySort(allContinuations);
         Print("");
         Print("  Max Favorable Excursion from entry (ATR):");
         Print("    25th percentile: ", DoubleToString(allContinuations[(int)(n*0.25)], 2), "x ATR");
         Print("    50th percentile: ", DoubleToString(allContinuations[(int)(n*0.50)], 2), "x ATR (median)");
         Print("    75th percentile: ", DoubleToString(allContinuations[(int)(n*0.75)], 2), "x ATR");
         if(n > 10)
            Print("    90th percentile: ", DoubleToString(allContinuations[(int)(n*0.90)], 2), "x ATR");
         Print("    Max:             ", DoubleToString(allContinuations[n-1], 2), "x ATR");
      }

      // Recommendation
      Print("");
      if(avgCont > 2.0)
         Print("  >>> RECOMMENDATION: Increase TP! Price continues ", DoubleToString(avgCont, 1), "x ATR after current TP <<<");
      else if(avgCont > 1.0)
         Print("  >>> RECOMMENDATION: Consider partial close at current TP + trail remainder <<<");
      else if(avgCont > 0)
         Print("  >>> RECOMMENDATION: Current TP is good, small continuation after <<<");
      else
         Print("  >>> RECOMMENDATION: Current TP is optimal, price often reverses after <<<");
   }
   else
   {
      Print("  No TP hits to analyze (all trades hit SL)");
   }

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
