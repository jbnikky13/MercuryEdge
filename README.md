# MercuryEdge

Technical-analysis trade setup engine for **Forex and Commodities**.

MercuryEdge is a signal-only system. It does not place trades or connect to a broker for execution.

## What it does

- Scans liquid FX pairs and major commodities
- Combines market trend, EMA structure, RSI, MACD, ATR, support/resistance and breakout/retest logic
- Scores setups instead of requiring a single indicator to trigger
- Calculates entry, stop loss, TP1, TP2 and risk/reward
- Filters weak or structurally invalid setups
- Produces concise Telegram-ready signals
- Keeps the architecture ready for scheduled GitHub Actions runs and future performance auditing

## Initial markets

### Forex
EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, NZDUSD, USDCAD, EURGBP, EURJPY, GBPJPY, AUDJPY, CADJPY, EURCHF, GBPCHF

### Commodities
XAUUSD, XAGUSD, USOIL, UKOIL, NATGAS, COPPER

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
Telegram / console output
```

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

Copy `.env.example` to `.env` when Telegram delivery is enabled. The first version can run without Telegram credentials and will print setups to the console.

## Important

MercuryEdge is an analytical/research tool, not financial advice. Backtest and paper-trade signals before risking capital.
