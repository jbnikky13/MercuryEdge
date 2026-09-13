# MercuryEdge

Technical-analysis trade setup engine for **Forex and Commodities**.

MercuryEdge is a signal-only research system. It does not place trades or connect to a broker for execution.

## What it does

- Scans liquid FX pairs and major commodities
- Combines market trend, EMA structure, RSI, MACD, ATR, support/resistance and breakout/retest logic
- Scores setups instead of relying on one indicator
- Calculates entry, stop loss, TP1, TP2 and risk/reward
- Publishes only the highest-ranked setups
- Sends concise Telegram-ready signals
- Records published setups in a persistent JSONL journal
- Includes a forward-looking historical backtester with a conservative same-candle rule
- Skips weekends, major US market holidays, late Friday sessions and late sessions on selected early-close days

## Initial markets

### Forex
EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, NZDUSD, USDCAD, EURGBP, EURJPY, GBPJPY, AUDJPY, CADJPY, EURCHF, GBPCHF

### Commodities
XAUUSD, XAGUSD, USOIL, UKOIL, NATGAS, COPPER

## Market timing

The scheduled workflow runs at **09:30, 14:30 and 19:30 WAT Monday-Thursday**, and **09:30 and 14:30 WAT on Friday**. GitHub Actions schedules are UTC, so the workflow uses UTC cron expressions and the application performs a second market-session/holiday check before scanning.

The timing is deliberately conservative. FX is generally a 24/5 market, while commodity contracts have exchange-specific daily breaks and holiday schedules. CME's published 2026 FX Spot+ schedule, for example, runs Sunday-Friday with a daily break, and CME publishes instrument-specific holiday hours. MercuryEdge therefore avoids late-Friday and major-holiday conditions rather than pretending every broker and instrument has identical hours. citehttps://www.cmegroup.com/trading-hours.html

US equity/market holidays are also used as a conservative liquidity filter. NYSE publishes the official yearly holiday and early-close calendar. citehttps://www.nyse.com/markets/hours-calendars

## Architecture

```text
Market data
   ↓
Normalization
   ↓
Indicators
   ↓
Trend + structure analysis
   ↓
Setup detection
   ↓
Risk / reward calculation
   ↓
Setup scoring
   ↓
Top signals
   ↓
Signal journal
   ↓
Telegram / console output
```

## Backtesting

Run a historical audit locally with:

```bash
python -m mercuryedge.backtest
```

Or choose a different forward horizon:

```bash
python -m mercuryedge.backtest --horizon 48
```

The backtester walks forward candle-by-candle and never uses future candles when creating a setup. If TP and SL are both touched in the same candle, **SL wins** because intrabar ordering is unknown. This makes the audit intentionally conservative.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m mercuryedge
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

## Configuration

Copy `.env.example` to `.env` when Telegram delivery is enabled.

```text
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
MERCURY_PERIOD=6mo
MERCURY_INTERVAL=1h
MERCURY_MAX_SETUPS=5
```

## Journal

Published signals are written to:

```text
data/journal.jsonl
```

GitHub Actions commits the updated journal back to `main` after a successful scan. This gives us a growing dataset for the next phase: automated outcome tracking, win rate, TP1/TP2/SL statistics, MFE/MAE and strategy calibration.

## Important

MercuryEdge is an analytical/research tool, not financial advice. Backtest and paper-trade signals before risking capital.
