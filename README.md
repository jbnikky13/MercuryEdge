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

The timing is deliberately conservative. FX is generally a 24/5 market, while commodity contracts have exchange-specific daily breaks and holiday schedules. CME publishes instrument-specific FX and commodity holiday/trading hours, so MercuryEdge avoids late-Friday and major-holiday conditions rather than pretending every broker and instrument has identical hours.

US market holidays are also used as a conservative liquidity filter. NYSE publishes the official yearly holiday and early-close calendar.

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

## Optional Longbridge quote enrichment

MercuryEdge can optionally fetch supplemental security quotes through the authenticated Longbridge CLI.

This is a **quote-only context feed**. It does not replace the existing candle provider for FX or commodities, create or rank setups, or access Longbridge trading APIs.

### Authenticate Longbridge

Authenticate the Longbridge CLI in the runtime:

```bash
longbridge auth login
longbridge check
```

### Configure supported securities

Choose securities supported by your Longbridge account and quote permissions:

```bash
export MERCURY_LONGBRIDGE_SYMBOLS="NVDA.US,AAPL.US"
```

Symbols use Longbridge format, such as:

- `NVDA.US` — NVIDIA
- `AAPL.US` — Apple
- `700.HK` — Tencent

The configured list is optional. An empty value keeps supplemental quotes disabled.

### Fetch quote snapshots

Fetch a quote-only snapshot for the configured securities:

```bash
python -m mercuryedge.longbridge_data
```

The command invokes:

```bash
longbridge quote NVDA.US AAPL.US --format json
```

The actual symbols are determined by `MERCURY_LONGBRIDGE_SYMBOLS`.

The returned JSON can include:

- Last traded price
- Previous close
- Opening, high and low prices
- Trading volume and turnover
- Trading status
- Pre-market quote data, when available
- Post-market quote data, when available
- Overnight quote data, when available

### Timestamp handling

Extended-hours timestamps supplied by Longbridge are retained as provider timestamps.

The separate `observed_at_utc` field records when MercuryEdge received the quote. It must not be interpreted as the exchange event timestamp.

### Integration boundaries

The main MercuryEdge signal scan logs supplemental Longbridge quotes when `MERCURY_LONGBRIDGE_SYMBOLS` is configured.

Longbridge quotes are contextual data only. They do not replace existing FX or commodity candle sources, create trading setups, change setup ranking, or modify signal scoring.

The adapter invokes the authenticated Longbridge CLI. It does not read, copy, or expose the CLI credential file and does not access trading or order-placement APIs.

### Deployment limitation

GitHub-hosted Actions runners are ephemeral and do not inherit the authenticated CLI session from Codespaces.

This integration does not configure hosted Actions authentication. Scheduled Actions will continue using the existing FX and commodity data path until a durable, secure Longbridge authentication approach is designed and tested.

Never copy CLI credentials, access tokens, refresh tokens, or authorization codes into source files, workflow YAML, issues, or chat.

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

## Audit-aligned signal intelligence

MercuryEdge now uses a strict **24-hour outcome horizon** so live outcome tracking and Signal Auditor settlement share the same lifecycle boundary. Published Telegram signals also expose machine-readable `SCORE`, `3D HIT RATE`, `CONFIRMATION`, and `AGREEMENT` fields so outcome analysis can measure which signal characteristics were actually present at publication time.

The current Signal Auditor sample is treated as calibration evidence, not as a permanent filter: no score band or cross-market rule is promoted from a small sample until it has sufficient observations and passes walk-forward validation. This prevents the system from overfitting to a handful of historical signals.

## Walk-forward strategy validation

The historical research workflow now runs a research-only chronological selector experiment after replaying the current rules. It uses a rolling 365-day training window followed by a 90-day unseen test window, advances by 90 days, purges training signals whose 24-hour outcome horizon reaches the test boundary, and suppresses overlapping same-symbol trades. A symbol/direction group is eligible only when it has at least 30 training trades and its training average exceeds the configured assumed costs plus a minimum edge buffer.

The workflow compares the existing baseline with the training-selected subset at assumed round-trip costs of 0R, 0.05R, and 0.10R. Results are saved to `research_data/walk-forward-folds.csv`, `research_data/walk-forward-summary.csv`, and `research_data/walk-forward-report.json`.

The historical replay also compares four exit policies: full position at TP1, full position at TP2, half at TP1 with the remainder at breakeven, and half at TP1 with the remainder retaining its original stop. It reports performance by symbol, direction, setup type, trend regime, volatility regime, and chronological period, including average R, win rate, profit factor, and drawdown where applicable. The trend regime uses EMA structure; the volatility regime uses a trailing ATR/price median to avoid looking ahead. These context slices are diagnostic and may be noisy when sample counts are small.

This experiment **does not change live signal generation or enable a filter**. Yahoo Finance history is a research proxy, cost levels are scenarios rather than broker quotes, and any apparent improvement must be independently reviewed and paper-tested before a production rule is considered.

## Journal

Published signals are written to:

```text
data/journal.jsonl
```

GitHub Actions commits the updated journal back to `main` after a successful scan. This gives us a growing dataset for the next phase: automated outcome tracking, win rate, TP1/TP2/SL statistics, MFE/MAE and strategy calibration.

## Important

MercuryEdge is an analytical/research tool, not financial advice. Backtest and paper-trade signals before risking capital.
