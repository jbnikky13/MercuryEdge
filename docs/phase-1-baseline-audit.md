# Phase 1 — MercuryEdge Baseline Validation

## Purpose

Measure the current strategy before changing indicators, scores, filters, or exit rules. This is a research baseline, not a strategy change.

## Initial repository findings

- `mercuryedge/analysis.py` currently uses EMA20/EMA50/EMA200, RSI, MACD, ATR, and rolling breakout levels to identify trend-continuation and breakout/breakdown candidates.
- `mercuryedge/upgrades.py` includes ADX/higher-timeframe regime filtering, exposure caps, exit-policy comparisons, bootstrap confidence intervals, and a rolling `walk_forward` helper.
- `data/walkforward.json` currently has zero folds.
- `data/calibration.json` currently has zero samples.
- The adaptive modifier is therefore not approved to influence scores based on validated walk-forward evidence.
- `mercuryedge/backtest.py` evaluates the base `analyze()` strategy at many consecutive candles. It does not currently demonstrate that the complete production pipeline (historical context, cross-market adjustments, audit filter, ADX/HTF gate, exposure selection, and live exit policy) improves unseen-data performance.

## Baseline rules

1. Preserve the current live strategy and thresholds while collecting the baseline.
2. Separate market-price history from labeled signal outcomes. A large price history is not equivalent to a large sample of settled production signals.
3. Build every feature from information available at signal time only. Never use future candles, future outcomes, or revised data to construct a prediction.
4. Evaluate chronological, walk-forward test windows. Thresholds or feature choices must be selected on the training window only; test windows remain unseen until evaluation.
5. Use the same market universe, signal eligibility, outcome horizon, stop/target definitions, and same-candle stop-first rule when comparing versions.
6. Include realistic spread, commission, and slippage assumptions where data supports them; otherwise label results gross of costs.
7. Report unresolved and excluded trades separately, including exclusion reasons. Never silently count unresolved trades as wins or losses.
8. Report sample counts and uncertainty alongside win rate. A small positive average R is not sufficient evidence of a durable edge.
9. Compare at minimum: (a) current base technical strategy, (b) current full production pipeline, and (c) simple reference baselines. Report expectancy in R, total R, drawdown, TP1/TP2/SL outcomes, number of signals, and performance by market/session.
10. Do not activate adaptive calibration or promote a filter unless it improves unseen test results consistently across multiple folds and remains credible after costs.

## Phase 1 acceptance criteria

- [ ] Confirm the exact outcome/journal schema and where Actions persist the complete dataset.
- [ ] Reconcile Signal Auditor's 55-signal report with raw signal/outcome rows, including the two price-feed mismatches.
- [ ] Verify that CADJPY's recorded settlement matches the actual forward-price path and timestamps.
- [ ] Validate entry timestamps, candle alignment, 24-hour horizon, TP/SL ordering, and exclusion rules.
- [ ] Produce reproducible baseline metrics with sample counts and uncertainty.
- [ ] Record current Git commit, data cutoff, market universe, configuration, and test-window boundaries.
- [ ] Keep live scoring and Telegram behavior unchanged during this audit.

## Important limitation

The Signal Auditor summary is an aggregate report, not sufficient by itself to reproduce all calculations. Phase 1 requires the underlying `audit-results.csv` plus the corresponding raw signal/outcome rows. If those files are not present in the repository, retrieve them from the workflow artifact or the machine that generated the report before drawing stronger conclusions.
