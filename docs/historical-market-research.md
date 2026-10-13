# Historical market data research pipeline

## Purpose
This job downloads historical OHLC data for every market in `mercuryedge.config.MARKETS`, replays the existing trend-continuation/breakout rules on hourly bars, and emits a research artifact. It does **not** alter production scores or enable real-money execution.

## Data sources and limitations
- Primary bootstrap source: Yahoo Finance via `yfinance`, using the exact tickers currently configured in MercuryEdge.
- Hourly history requested: 2 years. Yahoo's intraday retention limits vary by interval; the job records the actual start/end and reports missing markets rather than pretending the requested period was returned.
- Daily context requested: 10 years where available.
- For deeper minute/tick validation and broker-specific prices, use [Dukascopy Historical Data Export](https://www.dukascopy.com/swiss/english/marketwatch/historical/) and [HistData.com](https://www.histdata.com/). These sources have different instrument definitions and feeds. Map each instrument explicitly before merging data; never mix symbols silently.
- Raw research files are workflow artifacts, not committed to Git.

## Replay methodology
- The signal uses only indicators calculated from bars at or before its timestamp.
- Settlement inspects the next 24 hourly bars.
- If stop and target are both inside the same hourly bar, the replay conservatively counts the stop first because OHLC cannot reveal intrabar ordering.
- Results include three illustrative exit policies: TP1 full exit, TP2 full exit, and half at TP1 / half at TP2 (with a break-even stop after TP1).
- Results are gross R-multiples. Spread, slippage, financing, broker-specific contract sizing and latency are **not** included.
- Expired trades are marked to the final close after 24 bars. This is not a substitute for broker fills.

## What would qualify as an improvement
Do not change production thresholds based on in-sample returns. Add a candidate filter only after it beats the current baseline on chronological out-of-sample windows, has enough independent trades, survives conservative cost assumptions, and does not merely improve one instrument or one market regime. Report trade count, expectancy, profit factor, drawdown, confidence intervals, and costs. Preserve an untouched final holdout period.

## Running locally
```bash
pip install -r requirements.txt
python scripts/research_historical.py
```
