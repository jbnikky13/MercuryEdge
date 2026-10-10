# MercuryEdge upgrade pack - context for the AI assistant

## What this is
MercuryEdge is my Telegram trading-signal bot. Signal Auditor grades each signal: TP1/TP2 vs SL first hit. Signals are paper/research only.

## Findings from the audit (50 signals, Sep 29 - Oct 8 2026, 43 decided)
- Oct 7-8 batch: 1 win out of 7 decided; earlier period was about 42% wins.
- Every decided signal scoring <= 64 lost or reversed (0 wins out of 5).
- Both XAGUSD sells had cross-market confirmation -3 and both hit SL.
- VIX SELL was 0/4, DXY BUY was 0/2.
- NASDAQ prices differed between bot (~27,400) and auditor feed (~31,000): all 3 are DATA_MISMATCH.
- RUSSELL2000 returned no candles: all 3 NO_DATA.
- Exit rule test (filtered signals): hold to TP2/SL beat banking at TP1 and beat half+breakeven.
- Re-running the included CSV backtest on the ZIP snapshot gives average R (unfiltered -> filtered, hold to TP2): 0.09R -> 0.73R (27 filtered of 43 decided; small sample, in-sample).

## Files
- signal_filters.py: quality gate with minimum score 65, hit rate 50, analogues 40, confirmation >= 0, feed-vs-entry check, paused VIX SELL / DXY BUY, one signal per symbol per day.
- market_data.py: shared Yahoo Finance ticker/candle source; MercuryEdge strategy candles now use this provider too, with tickers aligned to `mercuryedge/config.py`.
- scheduler.py: four batches (01:30, 06:30, 16:30, 20:30 Africa/Lagos), session rules, 12h same-symbol window.
- bot_integration_example.py: illustrative integration for bot callers.
- stop_width_test.py: replay candles to test stop widths 1.0x/1.25x/1.5x/2.0x.
- audit-results.csv: audit data for local backtests.

## Known limits
- Yahoo ticker mappings should be checked against the intended instrument; NASDAQ is configured as ^NDX.
- Filter thresholds were fitted on 43 decided trades; re-check every ~100 decided signals.
- Early batches (01:30, 06:30) have limited audit history. The current Signal Auditor CSV is newer than this ZIP snapshot; use `signal-auditor-/data/audit-results.csv` for current outcomes.

These filters are research safeguards, not financial advice or a guarantee of outcomes.
