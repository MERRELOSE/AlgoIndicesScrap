//+------------------------------------------------------------------+
//|                                       WeekendGap_EA_v1.mq5        |
//|                 Weekend-gap trader: enter Fri close, exit Sun open|
//|                       AlgoIndicesScrap Project                    |
//+------------------------------------------------------------------+
//  Strategy:
//   - At Friday CloseUTC, measure the last N hours of price movement
//     (= "Friday body direction").
//   - Open a position in the direction dictated by InpStrategy:
//       continuation = bet gap goes same way as Friday body
//       fade         = bet gap goes against Friday body
//       auto         = use per-symbol default (metals=continuation,
//                      JPY crosses & scandis=fade)
//   - Exit at Sunday ReopenUTC + a few minutes (let spread normalize).
//
//  Validated universe (Deriv 2026-04-19 audit, net edge > 0.15%):
//       XAGUSD (cont 54%), XAGEUR (cont 56%), XAUUSD (cont 51%)
//  Other symbols: use at your own risk, audit spreads first.
//
//  Python equivalents: forex/src/gap_analysis.py, spread_check.py
//+------------------------------------------------------------------+
#property copyright "AlgoIndicesScrap"
#property version   "1.00"
#property description "Weekend gap EA - Fri close entry, Sun open exit. Auto direction per symbol."
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//+------------------------------------------------------------------+
//| INPUTS                                                            |
//+------------------------------------------------------------------+
input group "=== Risk / Sizing ==="
input double InpFixedLot        = 0.01;     // Fixed lot size (smallest by default)
input double InpRiskPercent     = 0.0;      // If >0, use % equity sizing (overrides fixed lot)
input double InpTPPercent       = 0.0;      // Take profit in % (0 = no TP, exit at Sunday open)
input int    InpMagic           = 790002;   // Magic number (bumped so history filters out v1 trades)

input group "=== Strategy ==="
input string InpStrategy            = "auto";  // "auto" / "continuation" / "fade"

//+------------------------------------------------------------------+
//| HARDCODED RISK & FILTER (tester .set overrides inputs, so we pin |
//| the critical values here. Edit source to retune.)                |
//+------------------------------------------------------------------+
#define FIXED_SL_PCT           0.5    // Stop loss = 0.5% of price
#define FIXED_MIN_BODY_PCT     1.00   // Ultra-directional only (>=1% Friday body over 20h)
#define FIXED_LOOKBACK_H       20     // Hours for Friday-body direction calc
#define FIXED_LONG_ONLY        true   // Block shorts (2022-26 XAGUSD shorts lost -$173 on 102 trades)

input group "=== Broker timezone ==="
// Deriv server time = UTC (GMT+0, no DST). Confirmed from live tick.time and docs.
// Other brokers differ (XM, IC Markets often GMT+2/+3). Override here if needed.
input int    InpBrokerGMTOffset  = 0;       // Hours to subtract from server time to get UTC

//+------------------------------------------------------------------+
//| HARDCODED WEEKEND TIMING (UTC summer-reference; winter +1h auto) |
//+------------------------------------------------------------------+
// Deriv XAU/XAG M1 data:
//   Friday close  = 20:44 UTC summer | 21:44 UTC winter  (NYSE 17:00 ET + DST)
//   Sunday reopen = 22:05 UTC summer | 23:05 UTC winter
// FIXED_MARKET_DST handles the 1-hour seasonal SHIFT OF MARKET HOURS
// (independent from the broker-server offset above).
#define FIXED_MARKET_DST        true
#define FIXED_ENTRY_DOW         5      // Friday
#define FIXED_ENTRY_HOUR_UTC    19     // summer UTC hour; winter auto +1h
#define FIXED_ENTRY_MIN_UTC     15
#define FIXED_ENTRY_WINDOW_MIN  45     // summer 19:15-20:00 UTC, winter 20:15-21:00 UTC
#define FIXED_EXIT_DOW          0      // Sunday
#define FIXED_EXIT_HOUR_UTC     22     // summer UTC hour; winter auto +1h
#define FIXED_EXIT_MIN_UTC      15     // 10-min buffer after reopen (spread easing)
#define FIXED_EXIT_WINDOW_MIN   60     // summer 22:15-23:15 UTC, winter 23:15-00:15 UTC

input group "=== Safety ==="
input int    InpMaxSpreadPtsEntry = 50;     // Skip entry if spread > this (in points)
input int    InpMaxSpreadPtsExit  = 500;    // Still exit at this much (we must close)
input bool   InpWarnIfUnvalidated = true;   // Warn if symbol not in {XAGUSD, XAGEUR, XAUUSD}

input group "=== Logging ==="
input bool   InpLogEachWeekend  = true;     // Print one line per weekend trade
input bool   InpPrintSummary    = true;     // Rich summary report at end of backtest

//+------------------------------------------------------------------+
//| GLOBALS                                                           |
//+------------------------------------------------------------------+
CTrade        g_trade;
CPositionInfo g_pos;

string  g_resolved_strategy = "continuation";  // resolved at OnInit
double  g_point = 0.0;
int     g_digits = 0;
string  g_symbol_class = "unknown"; // "metal_usd", "metal_eur", "jpy_cross", "scandi", "forex_major", "other"

datetime g_last_entry_attempt = 0;   // prevent double entries
datetime g_last_exit_attempt  = 0;

// --- Diagnostic counters (printed in summary) ---
int g_ticks_in_entry_window = 0;
int g_ticks_in_exit_window  = 0;
int g_entry_attempts        = 0;
int g_entry_skipped_spread  = 0;
int g_entry_skipped_body    = 0;
int g_entry_skipped_nodir   = 0;
int g_entry_opened          = 0;
int g_exits_triggered       = 0;
datetime g_first_friday_seen = 0;
datetime g_last_friday_seen  = 0;

// --- For per-weekend logging accumulation (printed at end) ---
struct WeekendTrade
{
   datetime entry_time;
   datetime exit_time;
   int      direction;        // +1 long, -1 short
   double   entry_price;
   double   exit_price;
   double   friday_body_pct;
   double   gap_pct;
   double   pnl;
   string   strategy_used;    // "continuation" / "fade"
   bool     is_win;
};
WeekendTrade g_trades[];
int          g_trades_n = 0;

//+------------------------------------------------------------------+
//| Symbol classification + default strategy                          |
//+------------------------------------------------------------------+
string ClassifySymbol(const string sym)
{
   if((StringFind(sym, "XAU") >= 0 || StringFind(sym, "XAG") >= 0) &&
      StringFind(sym, "EUR") >= 0) return "metal_eur";
   if(StringFind(sym, "XAU") >= 0 || StringFind(sym, "XAG") >= 0) return "metal_usd";
   if(StringFind(sym, "JPY") >= 0) return "jpy_cross";
   if(StringFind(sym, "NOK") >= 0 || StringFind(sym, "SEK") >= 0) return "scandi";
   if(StringLen(sym) == 6) return "forex_major";
   return "other";
}

string DefaultStrategyFor(const string cls)
{
   if(cls == "metal_usd" || cls == "metal_eur") return "continuation";
   if(cls == "jpy_cross") return "fade";
   if(cls == "scandi")    return "fade";
   return "continuation";
}

bool IsValidatedSymbol(const string sym)
{
   return (sym == "XAUUSD" || sym == "XAGUSD" || sym == "XAGEUR");
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

   // Resolve strategy
   string strat = InpStrategy;
   StringToLower(strat);
   if(strat == "auto")
      g_resolved_strategy = DefaultStrategyFor(g_symbol_class);
   else if(strat == "continuation" || strat == "fade")
      g_resolved_strategy = strat;
   else
   {
      Print("[WARN] Unknown InpStrategy='", InpStrategy, "' - defaulting to continuation");
      g_resolved_strategy = "continuation";
   }

   ArrayResize(g_trades, 0);
   g_trades_n = 0;

   Print("======================================================================");
   Print("  WEEKEND GAP EA v1.00 - INIT");
   Print("======================================================================");
   Print("  Symbol:            ", _Symbol, "  (class: ", g_symbol_class, ", digits: ", g_digits, ")");
   Print("  Broker GMT offset: ", InpBrokerGMTOffset, "h (Deriv=0, others may differ)");
   Print("  Resolved strategy: ", g_resolved_strategy);
   Print("  Lookback for body: ", FIXED_LOOKBACK_H, " hours  [HARDCODED]");
   Print("  Min body filter:   ", DoubleToString(FIXED_MIN_BODY_PCT, 3), "%  [HARDCODED]");
   Print("  Long-only filter:  ", FIXED_LONG_ONLY ? "ON  [HARDCODED]" : "OFF");
   Print("  Entry (summer UTC): Fri ", FIXED_ENTRY_HOUR_UTC, ":",
         (FIXED_ENTRY_MIN_UTC < 10 ? "0" : ""), FIXED_ENTRY_MIN_UTC,
         "  window=", FIXED_ENTRY_WINDOW_MIN, "min",
         (FIXED_MARKET_DST ? "  (winter: +1h auto)" : ""), "  [HARDCODED]");
   Print("  Exit  (summer UTC): Sun ", FIXED_EXIT_HOUR_UTC, ":",
         (FIXED_EXIT_MIN_UTC < 10 ? "0" : ""), FIXED_EXIT_MIN_UTC,
         "  window=", FIXED_EXIT_WINDOW_MIN, "min",
         (FIXED_MARKET_DST ? "  (winter: +1h auto)" : ""), "  [HARDCODED]");
   Print("  Lot size:          ", DoubleToString(InpFixedLot, 2),
         (InpRiskPercent > 0 ? "  (overridden by risk% = " + DoubleToString(InpRiskPercent, 2) + "%)" : ""));
   Print("  SL / TP:           ", DoubleToString(FIXED_SL_PCT, 2), "% [HARDCODED] / ",
         (InpTPPercent <= 0 ? "disabled (exit at Sun open)" : DoubleToString(InpTPPercent, 2) + "%"));
   Print("  Max spread (entry):", InpMaxSpreadPtsEntry, " pts");
   Print("  Magic:             ", InpMagic);

   if(InpWarnIfUnvalidated && !IsValidatedSymbol(_Symbol))
      Print("[WARN] ", _Symbol, " is NOT in the validated list {XAUUSD, XAGUSD, XAGEUR}. Running anyway.");

   Print("======================================================================");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(InpPrintSummary && MQLInfoInteger(MQL_TESTER))
      PrintSummaryReport();
}

//+------------------------------------------------------------------+
//| Time helpers                                                      |
//+------------------------------------------------------------------+
// Winter (Nov-Mar) shifts Friday close / Sunday reopen 1h later UTC (NYSE DST).
int _SeasonalHourShift(const MqlDateTime &dt_utc)
{
   if(!FIXED_MARKET_DST) return 0;
   return (dt_utc.mon >= 4 && dt_utc.mon <= 10) ? 0 : 1;  // winter = +1h
}

bool IsInEntryWindow(const MqlDateTime &dt_utc)
{
   if(dt_utc.day_of_week != FIXED_ENTRY_DOW) return false;
   int eff_hour = FIXED_ENTRY_HOUR_UTC + _SeasonalHourShift(dt_utc);
   int now_min = dt_utc.hour * 60 + dt_utc.min;
   int tgt_min = eff_hour * 60 + FIXED_ENTRY_MIN_UTC;
   return (now_min >= tgt_min && now_min <= tgt_min + FIXED_ENTRY_WINDOW_MIN);
}

bool IsInExitWindow(const MqlDateTime &dt_utc)
{
   int shift = _SeasonalHourShift(dt_utc);
   int eff_hour = FIXED_EXIT_HOUR_UTC + shift;
   int tgt_start = eff_hour * 60 + FIXED_EXIT_MIN_UTC;
   int tgt_end   = tgt_start + FIXED_EXIT_WINDOW_MIN;

   if(dt_utc.day_of_week == FIXED_EXIT_DOW && tgt_end < 24*60)
   {
      int now_min = dt_utc.hour * 60 + dt_utc.min;
      return (now_min >= tgt_start && now_min <= tgt_end);
   }
   if(tgt_end >= 24*60)  // winter: window can spill into Monday
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
//| Friday body direction                                             |
//+------------------------------------------------------------------+
bool ComputeFridayBody(double &body_pct, int &direction)
{
   double ref_open = iOpen(_Symbol, PERIOD_H1, FIXED_LOOKBACK_H);
   double cur_bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(ref_open <= 0 || cur_bid <= 0) return false;
   body_pct = (cur_bid - ref_open) / ref_open * 100.0;
   direction = (body_pct > 0 ? 1 : (body_pct < 0 ? -1 : 0));
   return true;
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

double CalcLotSize(const double sl_price_distance)
{
   if(InpRiskPercent <= 0.0 || sl_price_distance <= 0.0)
      return NormalizeLot(InpFixedLot);

   double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
   double tick_val = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_sz  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_val <= 0 || tick_sz <= 0) return NormalizeLot(InpFixedLot);

   double risk_money = equity * InpRiskPercent / 100.0;
   double loss_per_lot = (sl_price_distance / tick_sz) * tick_val;
   if(loss_per_lot <= 0) return NormalizeLot(InpFixedLot);
   double lot = risk_money / loss_per_lot;
   return NormalizeLot(lot);
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

//+------------------------------------------------------------------+
//| OnTick                                                            |
//+------------------------------------------------------------------+
void OnTick()
{
   // Server -> UTC using user-configured broker offset (Deriv = 0, confirmed).
   datetime now = TimeCurrent() - (datetime)(InpBrokerGMTOffset * 3600);
   MqlDateTime dt_utc; TimeToStruct(now, dt_utc);

   // Diagnostic: track Friday tick visibility
   if(dt_utc.day_of_week == FIXED_ENTRY_DOW)
   {
      if(g_first_friday_seen == 0) g_first_friday_seen = now;
      g_last_friday_seen = now;
   }

   bool in_entry = IsInEntryWindow(dt_utc);
   bool in_exit  = IsInExitWindow(dt_utc);
   if(in_entry) g_ticks_in_entry_window++;
   if(in_exit)  g_ticks_in_exit_window++;

   // Throttle to once a minute per action
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
//| Open weekend trade                                                |
//+------------------------------------------------------------------+
void TryOpenWeekendTrade(datetime now_utc)
{
   long spread_pts = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread_pts > InpMaxSpreadPtsEntry)
   {
      g_entry_skipped_spread++;
      if(InpLogEachWeekend)
         Print("[SKIP] ", TimeToString(now_utc, TIME_DATE|TIME_MINUTES),
               " spread=", spread_pts, "pts > ", InpMaxSpreadPtsEntry);
      return;
   }

   double body_pct; int direction;
   if(!ComputeFridayBody(body_pct, direction))
   {
      g_entry_skipped_nodir++;
      Print("[SKIP] Could not compute Friday body");
      return;
   }
   if(MathAbs(body_pct) < FIXED_MIN_BODY_PCT)
   {
      g_entry_skipped_body++;
      if(InpLogEachWeekend)
         Print("[SKIP] ", TimeToString(now_utc, TIME_DATE|TIME_MINUTES),
               " body=", DoubleToString(body_pct, 3), "% < min ", DoubleToString(FIXED_MIN_BODY_PCT, 3), "%");
      return;
   }

   // Strategy -> trade direction
   int trade_dir = direction;  // continuation
   if(g_resolved_strategy == "fade") trade_dir = -direction;
   if(trade_dir == 0) { g_entry_skipped_nodir++; return; }

   // Long-only filter (baseline says XAGUSD shorts lose on 2022-26 data)
   if(FIXED_LONG_ONLY && trade_dir < 0)
   {
      g_entry_skipped_nodir++;
      if(InpLogEachWeekend)
         Print("[SKIP] ", TimeToString(now_utc, TIME_DATE|TIME_MINUTES),
               " SHORT blocked by FIXED_LONG_ONLY (body=", DoubleToString(body_pct, 3), "%)");
      return;
   }

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double entry_price = (trade_dir > 0 ? ask : bid);

   double sl_price = 0, tp_price = 0;
   double sl_dist = entry_price * FIXED_SL_PCT / 100.0;
   if(trade_dir > 0)
   {
      sl_price = NormalizeDouble(entry_price - sl_dist, g_digits);
      if(InpTPPercent > 0) tp_price = NormalizeDouble(entry_price + entry_price * InpTPPercent / 100.0, g_digits);
   }
   else
   {
      sl_price = NormalizeDouble(entry_price + sl_dist, g_digits);
      if(InpTPPercent > 0) tp_price = NormalizeDouble(entry_price - entry_price * InpTPPercent / 100.0, g_digits);
   }

   double lot = CalcLotSize(sl_dist);
   string comment = StringFormat("WGAP %s body=%.2f%%", g_resolved_strategy, body_pct);

   bool ok;
   if(trade_dir > 0) ok = g_trade.Buy(lot, _Symbol, ask, sl_price, tp_price, comment);
   else              ok = g_trade.Sell(lot, _Symbol, bid, sl_price, tp_price, comment);

   if(ok)
   {
      g_entry_opened++;
      // Seed trade record (pnl filled on close)
      g_trades_n++;
      ArrayResize(g_trades, g_trades_n);
      g_trades[g_trades_n-1].entry_time     = now_utc;
      g_trades[g_trades_n-1].direction      = trade_dir;
      g_trades[g_trades_n-1].entry_price    = entry_price;
      g_trades[g_trades_n-1].friday_body_pct = body_pct;
      g_trades[g_trades_n-1].strategy_used  = g_resolved_strategy;

      if(InpLogEachWeekend)
         Print("[OPEN] ", TimeToString(now_utc, TIME_DATE|TIME_MINUTES),
               " ", (trade_dir > 0 ? "BUY" : "SELL"),
               " ", DoubleToString(lot, 2), " @ ", DoubleToString(entry_price, g_digits),
               " | body=", DoubleToString(body_pct, 3), "%",
               " | SL=", DoubleToString(sl_price, g_digits),
               " | spread=", spread_pts, "pts",
               " | strat=", g_resolved_strategy);
   }
   else
      Print("[ERROR] Open failed: ", g_trade.ResultRetcode(), " - ", g_trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
//| Close weekend trade                                               |
//+------------------------------------------------------------------+
void TryCloseWeekendTrade(datetime now_utc)
{
   long spread_pts = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread_pts > InpMaxSpreadPtsExit)
   {
      // Still try after warning - we MUST close before Monday
      Print("[WARN] Spread ", spread_pts, " > exit max ", InpMaxSpreadPtsExit, " - closing anyway");
   }

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Symbol() != _Symbol) continue;
      if(g_pos.Magic()  != InpMagic) continue;

      double entry_price = g_pos.PriceOpen();
      double cur_bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double cur_ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double exit_price = (g_pos.PositionType() == POSITION_TYPE_BUY ? cur_bid : cur_ask);
      double gap_pct = (exit_price - entry_price) / entry_price * 100.0;
      if(g_pos.PositionType() == POSITION_TYPE_SELL) gap_pct = -gap_pct;

      if(!g_trade.PositionClose(g_pos.Ticket()))
      {
         Print("[ERROR] Close failed: ", g_trade.ResultRetcode(), " - ", g_trade.ResultRetcodeDescription());
         continue;
      }

      // Fill in the last trade record
      if(g_trades_n > 0)
      {
         int k = g_trades_n - 1;
         g_trades[k].exit_time  = now_utc;
         g_trades[k].exit_price = exit_price;
         g_trades[k].gap_pct    = gap_pct;
         g_trades[k].pnl        = g_pos.Profit() + g_pos.Swap() + g_pos.Commission();
         g_trades[k].is_win     = (g_trades[k].pnl > 0);
      }

      if(InpLogEachWeekend)
         Print("[CLOSE] ", TimeToString(now_utc, TIME_DATE|TIME_MINUTES),
               " exit=", DoubleToString(exit_price, g_digits),
               " | gap_captured=", DoubleToString(gap_pct, 3), "%",
               " | spread=", spread_pts, "pts");
   }
}

//+------------------------------------------------------------------+
//| OnTester - ensures summary still prints on tester finalization    |
//+------------------------------------------------------------------+
double OnTester()
{
   return 0.0;
}

//+------------------------------------------------------------------+
//| SUMMARY REPORT                                                    |
//+------------------------------------------------------------------+
void PrintSummaryReport()
{
   // --- Diagnostic counters always printed (helps debug zero-trade runs) ---
   Print("======================================================================");
   Print("  WEEKEND GAP EA v1.00 - DIAGNOSTIC COUNTERS");
   Print("======================================================================");
   Print("  Ticks seen in entry window:  ", g_ticks_in_entry_window);
   Print("  Ticks seen in exit  window:  ", g_ticks_in_exit_window);
   Print("  First Friday tick UTC:       ",
         g_first_friday_seen > 0 ? TimeToString(g_first_friday_seen, TIME_DATE|TIME_MINUTES) : "NEVER");
   Print("  Last Friday tick UTC:        ",
         g_last_friday_seen > 0 ? TimeToString(g_last_friday_seen, TIME_DATE|TIME_MINUTES) : "NEVER");
   Print("  Entry attempts:              ", g_entry_attempts);
   Print("    skipped - spread too wide: ", g_entry_skipped_spread);
   Print("    skipped - body too small:  ", g_entry_skipped_body);
   Print("    skipped - no direction:    ", g_entry_skipped_nodir);
   Print("    opened successfully:       ", g_entry_opened);
   Print("  Exits triggered:             ", g_exits_triggered);
   Print("");

   if(!HistorySelect(0, TimeCurrent())) return;
   int totalDeals = HistoryDealsTotal();
   if(totalDeals == 0)
   {
      Print("[SUMMARY] No deals recorded. Check diagnostic counters above.");
      return;
   }

   // --- Aggregates ---
   int totalTrades = 0, wins = 0, losses = 0, longTr = 0, shortTr = 0, longWins = 0, shortWins = 0;
   double grossProfit = 0, grossLoss = 0, totalProfit = 0, longPnl = 0, shortPnl = 0;
   double maxWin = 0, maxLoss = 0;
   int maxWinStreak = 0, maxLossStreak = 0, curWinStreak = 0, curLossStreak = 0;
   double runningBal = 0, peakBal = 0, maxDD = 0;
   int tpCount = 0, slCount = 0, otherCount = 0;
   double tpPnl = 0, slPnl = 0, otherPnl = 0;

   // Monthly
   int    monthKeys[]; double monthPnl[]; int monthTrades[]; int monthWins[];
   int    numMonths = 0;

   // Friday body size buckets: small (<0.3%), medium (0.3-0.8%), large (>0.8%)
   int bucketCount[3] = {0, 0, 0};
   int bucketWins[3]  = {0, 0, 0};
   double bucketPnl[3] = {0, 0, 0};
   string bucketNames[3] = {"small(<0.3%)", "medium(0.3-0.8%)", "large(>0.8%)"};

   // Continuation vs fade breakdown
   int contCount = 0, contWins = 0, fadeCount = 0, fadeWins = 0;
   double contPnl = 0, fadePnl = 0;

   for(int i = 0; i < totalDeals; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(HistoryDealGetString(ticket, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != InpMagic) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;

      double profit = HistoryDealGetDouble(ticket, DEAL_PROFIT);
      double swap   = HistoryDealGetDouble(ticket, DEAL_SWAP);
      double comm   = HistoryDealGetDouble(ticket, DEAL_COMMISSION);
      double net    = profit + swap + comm;
      ENUM_DEAL_REASON reason = (ENUM_DEAL_REASON)HistoryDealGetInteger(ticket, DEAL_REASON);
      ENUM_DEAL_TYPE   dtype  = (ENUM_DEAL_TYPE)HistoryDealGetInteger(ticket, DEAL_TYPE);
      datetime exitTime = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);

      totalTrades++;
      totalProfit += net;
      runningBal += net;
      if(runningBal > peakBal) peakBal = runningBal;
      double dd = peakBal - runningBal;
      if(dd > maxDD) maxDD = dd;

      bool isWin = (net > 0);
      if(isWin)  { wins++;   grossProfit += net; if(net > maxWin) maxWin = net;
                    curWinStreak++; if(curWinStreak > maxWinStreak) maxWinStreak = curWinStreak; curLossStreak = 0; }
      else        { losses++; grossLoss += MathAbs(net); if(net < maxLoss) maxLoss = net;
                    curLossStreak++; if(curLossStreak > maxLossStreak) maxLossStreak = curLossStreak; curWinStreak = 0; }

      // OUT deal: for a closed BUY the OUT deal is a SELL. Flip logic to get original side.
      bool wasLong = (dtype == DEAL_TYPE_SELL);  // OUT side flipped
      if(wasLong) { longTr++;  longPnl  += net; if(isWin) longWins++; }
      else        { shortTr++; shortPnl += net; if(isWin) shortWins++; }

      if(reason == DEAL_REASON_TP)      { tpCount++;    tpPnl    += net; }
      else if(reason == DEAL_REASON_SL) { slCount++;    slPnl    += net; }
      else                               { otherCount++; otherPnl += net; }

      // Find entry comment to parse strategy + body pct
      ulong posId = HistoryDealGetInteger(ticket, DEAL_POSITION_ID);
      string entryComment = "";
      double bodyPct = 0.0;
      for(int j = 0; j < totalDeals; j++)
      {
         ulong t2 = HistoryDealGetTicket(j);
         if(HistoryDealGetInteger(t2, DEAL_POSITION_ID) == posId &&
            (ENUM_DEAL_ENTRY)HistoryDealGetInteger(t2, DEAL_ENTRY) == DEAL_ENTRY_IN)
         {
            entryComment = HistoryDealGetString(t2, DEAL_COMMENT);
            break;
         }
      }

      // parse body=xxx%
      int pos = StringFind(entryComment, "body=");
      if(pos >= 0)
      {
         string tail = StringSubstr(entryComment, pos + 5);
         int pct_pos = StringFind(tail, "%");
         if(pct_pos > 0) bodyPct = StringToDouble(StringSubstr(tail, 0, pct_pos));
      }
      bool isCont = (StringFind(entryComment, "continuation") >= 0);
      bool isFade = (StringFind(entryComment, "fade") >= 0);
      if(isCont) { contCount++;  contPnl  += net; if(isWin) contWins++; }
      if(isFade) { fadeCount++;  fadePnl  += net; if(isWin) fadeWins++; }

      double absBody = MathAbs(bodyPct);
      int bkt = (absBody < 0.3 ? 0 : (absBody < 0.8 ? 1 : 2));
      bucketCount[bkt]++;
      bucketPnl[bkt] += net;
      if(isWin) bucketWins[bkt]++;

      // Monthly
      MqlDateTime dtm; TimeToStruct(exitTime, dtm);
      int mk = dtm.year * 100 + dtm.mon;
      int mi = -1;
      for(int m = 0; m < numMonths; m++) if(monthKeys[m] == mk) { mi = m; break; }
      if(mi == -1)
      {
         numMonths++;
         ArrayResize(monthKeys, numMonths);   ArrayResize(monthPnl, numMonths);
         ArrayResize(monthTrades, numMonths); ArrayResize(monthWins, numMonths);
         mi = numMonths - 1;
         monthKeys[mi] = mk; monthPnl[mi] = 0; monthTrades[mi] = 0; monthWins[mi] = 0;
      }
      monthPnl[mi] += net; monthTrades[mi]++; if(isWin) monthWins[mi]++;
   }

   if(totalTrades == 0) { Print("[SUMMARY] No trades for this symbol/magic."); return; }

   double winRate = (double)wins / totalTrades * 100.0;
   double pf      = (grossLoss > 0) ? grossProfit / grossLoss : 99;
   double avgWin  = (wins > 0) ? grossProfit / wins : 0;
   double avgLoss = (losses > 0) ? grossLoss / losses : 0;
   double exp_    = (winRate/100.0 * avgWin) - ((100.0-winRate)/100.0 * avgLoss);
   double initBal = TesterStatistics(STAT_INITIAL_DEPOSIT);
   double retPct  = (initBal > 0) ? totalProfit / initBal * 100.0 : 0;
   double rr      = (avgLoss > 0) ? avgWin / avgLoss : 0;

   Print("======================================================================");
   Print("  WEEKEND GAP EA v1.00 - BACKTEST SUMMARY REPORT");
   Print("======================================================================");
   Print("");
   Print("--- SYMBOL CONTEXT ---");
   Print("  Symbol:              ", _Symbol, "  (class: ", g_symbol_class, ")");
   Print("  Resolved strategy:   ", g_resolved_strategy);
   Print("  Validated universe:  ", IsValidatedSymbol(_Symbol) ? "YES" : "NO (unverified symbol)");
   Print("");
   Print("--- PERFORMANCE ---");
   Print("  Initial Balance:     $", DoubleToString(initBal, 2));
   Print("  Final Balance:       $", DoubleToString(initBal + totalProfit, 2));
   Print("  Net Profit:          $", DoubleToString(totalProfit, 2));
   Print("  Return:              ", DoubleToString(retPct, 2), "%");
   Print("  Max Drawdown:        $", DoubleToString(maxDD, 2));
   Print("  Profit Factor:       ", DoubleToString(pf, 2));
   Print("  Expectancy/trade:    $", DoubleToString(exp_, 2));
   Print("");
   Print("--- TRADES ---");
   Print("  Total Trades:        ", totalTrades);
   Print("  Winners:             ", wins,   " (", DoubleToString(winRate, 1), "%)");
   Print("  Losers:              ", losses, " (", DoubleToString(100-winRate, 1), "%)");
   Print("  Avg Winner:          $", DoubleToString(avgWin, 2));
   Print("  Avg Loser:           $", DoubleToString(avgLoss, 2));
   Print("  Best Trade:          $", DoubleToString(maxWin, 2));
   Print("  Worst Trade:         $", DoubleToString(maxLoss, 2));
   Print("  Max Win Streak:      ", maxWinStreak);
   Print("  Max Loss Streak:     ", maxLossStreak);
   Print("  Realized R:R:        1:", DoubleToString(rr, 2));
   Print("");
   Print("--- EXIT REASONS ---");
   Print("  Take Profit:         ", tpCount,    " trades | $", DoubleToString(tpPnl, 2));
   Print("  Stop Loss:           ", slCount,    " trades | $", DoubleToString(slPnl, 2));
   Print("  Sunday close / other:", otherCount, " trades | $", DoubleToString(otherPnl, 2));
   Print("");
   Print("--- DIRECTION BREAKDOWN ---");
   if(longTr > 0)
      Print("  LONG:  n=", longTr,  " | WR=", DoubleToString((double)longWins/longTr*100, 1),
            "% | PnL=$", DoubleToString(longPnl, 2));
   if(shortTr > 0)
      Print("  SHORT: n=", shortTr, " | WR=", DoubleToString((double)shortWins/shortTr*100, 1),
            "% | PnL=$", DoubleToString(shortPnl, 2));
   Print("");
   Print("--- STRATEGY BREAKDOWN ---");
   if(contCount > 0)
      Print("  continuation: n=", contCount, " | WR=", DoubleToString((double)contWins/contCount*100, 1),
            "% | PnL=$", DoubleToString(contPnl, 2),
            " | Avg=$", DoubleToString(contPnl/contCount, 2));
   if(fadeCount > 0)
      Print("  fade:         n=", fadeCount, " | WR=", DoubleToString((double)fadeWins/fadeCount*100, 1),
            "% | PnL=$", DoubleToString(fadePnl, 2),
            " | Avg=$", DoubleToString(fadePnl/fadeCount, 2));
   Print("");
   Print("--- FRIDAY BODY SIZE BUCKETS ---");
   for(int b = 0; b < 3; b++)
   {
      if(bucketCount[b] == 0) { Print("  ", bucketNames[b], ": n=0"); continue; }
      double bwr = (double)bucketWins[b] / bucketCount[b] * 100.0;
      Print("  ", bucketNames[b], ": n=", bucketCount[b],
            " | WR=", DoubleToString(bwr, 1), "%",
            " | PnL=$", DoubleToString(bucketPnl[b], 2),
            " | Avg=$", DoubleToString(bucketPnl[b]/bucketCount[b], 2));
   }
   Print("");

   // Sort months chronologically
   for(int a = 0; a < numMonths - 1; a++)
      for(int b = a + 1; b < numMonths; b++)
         if(monthKeys[b] < monthKeys[a])
         {
            int tk = monthKeys[a]; monthKeys[a] = monthKeys[b]; monthKeys[b] = tk;
            double tp = monthPnl[a]; monthPnl[a] = monthPnl[b]; monthPnl[b] = tp;
            int tt = monthTrades[a]; monthTrades[a] = monthTrades[b]; monthTrades[b] = tt;
            int tw = monthWins[a]; monthWins[a] = monthWins[b]; monthWins[b] = tw;
         }
   Print("--- MONTHLY BREAKDOWN ---");
   int profMonths = 0; double cum = initBal;
   for(int m = 0; m < numMonths; m++)
   {
      int yr = monthKeys[m]/100, mn = monthKeys[m]%100;
      double mwr = (monthTrades[m] > 0) ? (double)monthWins[m]/monthTrades[m]*100.0 : 0;
      cum += monthPnl[m];
      string mk = (monthPnl[m] > 0 ? "+" : (monthPnl[m] < 0 ? "-" : "="));
      Print("  ", yr, "-", (mn<10?"0":""), mn,
            " | PnL=$", DoubleToString(monthPnl[m], 2),
            " | trades=", monthTrades[m],
            " | WR=", DoubleToString(mwr, 0), "%",
            " | bal=$", DoubleToString(cum, 2), "  ", mk);
      if(monthPnl[m] > 0) profMonths++;
   }
   Print("  Profitable Months:   ", profMonths, "/", numMonths,
         " (", DoubleToString((double)profMonths/MathMax(1,numMonths)*100.0, 0), "%)");
   Print("");
   Print("--- SETTINGS USED ---");
   Print("  Lot / Risk%:         ", DoubleToString(InpFixedLot, 2),
         " / ", DoubleToString(InpRiskPercent, 2), "%");
   Print("  SL / TP %:           ", DoubleToString(FIXED_SL_PCT, 2), " [hardcoded] / ",
         DoubleToString(InpTPPercent, 2));
   Print("  Broker offset:       ", InpBrokerGMTOffset, "h");
   Print("  Strategy input:      ", InpStrategy, " (resolved: ", g_resolved_strategy, ")");
   Print("  Body lookback:       ", FIXED_LOOKBACK_H, "h  [hardcoded], min=",
         DoubleToString(FIXED_MIN_BODY_PCT, 3), "%  [hardcoded]");
   Print("  Entry window (UTC):  day=", FIXED_ENTRY_DOW, " ",
         FIXED_ENTRY_HOUR_UTC, ":", (FIXED_ENTRY_MIN_UTC<10?"0":""), FIXED_ENTRY_MIN_UTC,
         " +/-", FIXED_ENTRY_WINDOW_MIN, "min  [hardcoded]");
   Print("  Exit window (UTC):   day=", FIXED_EXIT_DOW, " ",
         FIXED_EXIT_HOUR_UTC, ":", (FIXED_EXIT_MIN_UTC<10?"0":""), FIXED_EXIT_MIN_UTC,
         " +/-", FIXED_EXIT_WINDOW_MIN, "min  [hardcoded]");
   Print("  Spread caps:         entry<=", InpMaxSpreadPtsEntry, "pts, exit<=", InpMaxSpreadPtsExit, "pts");
   Print("  Magic:               ", InpMagic);
   Print("");
   Print("======================================================================");
   Print("  Copy everything above and paste into the chat for analysis");
   Print("======================================================================");
}
