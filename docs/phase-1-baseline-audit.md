# Phase 1 — MercuryEdge Baseline Validation

## Purpose

Measure the current strategy before changing indicators, scores, filters, or exit rules. This is a research baseline, not a strategy change.

## Initial repository findings

- `mercuryedge/analysis.py` uses EMA20/EMA50/EMA200, RSI, MACD, ATR, and rolling breakout levels to identify trend-continuation and breakout/breakdown candidates.
- `mercuryedge/upgrades.py` includes ADX/higher-timeframe regime filtering, exposure caps, exit-policy comparisons, bootstrap confidence intervals, and a rolling `walk_forward` helper.
- `data/walkforward.json` currently has zero folds.
- `data/calibration.json` currently has zero samples.
- The adaptive modifier is disabled (`adaptive_enabled: false`) and is not approved to influence scores without validated walk-forward evidence.
- `mercuryedge/backtest.py` evaluates the base `analyze()` strategy across consecutive candles. It does not yet demonstrate that the complete production pipeline (historical context, cross-market adjustments, audit filter, ADX/HTF gate, exposure selection, session logic, and live exit policy) improves unseen-data performance.

## Signal Auditor CSV reconciliation — first pass

Source: Signal Auditor `data/audit-results.csv` on its `main` branch, 55 rows. This section records the file as inspected on 2026-10-13; rerun the audit when the source dataset changes.

| Classification | Count | Share of 53 decided rows |
| --- | ---: | ---: |
| TP2 | 15 | 28.3% |
| SL before TP1 | 26 | 49.1% |
| TP1 then SL | 8 | 15.1% |
| TP1 only / unresolved terminal outcome | 4 | 7.5% |
| DATA_MISMATCH (excluded) | 2 | excluded |

- Total records: 55; decided records used in the outcome denominator: 53; two NASDAQ-related `DATA_MISMATCH` records remain excluded.
- TP1 was reached before SL in 27/53 records (50.9%). This is a path/outcome statistic, not a guarantee of positive net returns.
- Mean reported/provider hit-rate field across the 53 decided records: approximately 67.1%. This is a claimed input field, not an independently validated probability.
- Simple hypothetical TP1 exit model: +5.105R total, +0.096R per decided signal (n=53), treating any TP1-first outcome as +TP1 R and an SL-first outcome as -1R.
- Simple TP2-only model: -0.162R total, -0.003R per signal (n=49 eligible), treating TP2 as +TP2 R and SL / TP1-then-SL as -1R; TP1-only records are omitted from this simplified model.
- These are simplified calculations from recorded labels and entry/stop/target distances. They are not audited live returns and do not include spread, commission, slippage, partial-close rules, or independent candle-by-candle verification. In particular, TP1-then-SL does not model the production `half_be` or other partial-exit policies.

### Horizon and data-quality blockers

- MercuryEdge documents a strict 24-hour trade horizon, while Signal Auditor's `config.py` and `settle.py` default to 72 hours. The current outcome report therefore is not directly comparable to the stated MercuryEdge policy.
- Eleven records have a TP1 timestamp or final resolution beyond 24 hours. Ten final resolutions are after 24 hours; one additional TP1-only record reaches TP1 after 24 hours. Some TP1-then-SL records reach TP1 before 24 hours but resolve to SL after the cutoff.
- Do not fix these by merely changing the outcome labels. Re-settle them against original minute candles through the exact 24-hour cutoff, using the same stop/target touch ordering and candle-alignment rules as production. A TP1-before-cutoff / SL-after-cutoff trade may need to be classified as TP1-only at cutoff if no other eligible exit occurs before expiry.
- Two NASDAQ records show a substantial discrepancy between the signal entry and the reference price feed (reference around 30,924 / 31,019 versus entry around 27,313 / 27,439). Keep these excluded until the exact index instrument and feed are identified.
- The 2026-10-13 CADJPY SELL record in Signal Auditor (entry 110.86, SL 110.99; marked SL at 108.45 minutes) closely matches an OPEN CADJPY SELL in MercuryEdge's `data/journal.jsonl` (entry 110.863998, SL 110.989818, from the 06:00 UTC batch). This is a strong record-level match, but it does not independently verify the minute price path, spread-adjusted stop, or first-touch order. Reconcile journal status with the source candles before marking it confirmed.
- The CSV contains settled labels but not the underlying minute OHLC path required to reproduce the settlement. Obtain the original market candles and source signal payloads / workflow artifact before making a stronger claim.

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

## Required next steps

1. Fix the measurement contract first: one explicit 24-hour expiry definition, timestamp timezone/alignment, same-candle TP/SL ordering, spread/cost treatment, and terminal classifications.
2. Retrieve the raw minute candles and source signal payloads needed to re-settle all 55 rows. Preserve the original outcome and the re-settled outcome side by side; do not overwrite historical labels silently.
3. Resolve the two NASDAQ instrument/feed mismatches and the CADJPY journal-versus-audit status discrepancy.
4. Build a reproducible chronological evaluation with common eligibility and costs: (a) simple reference baseline, (b) base technical strategy, and (c) complete production pipeline. Report fold-level and aggregate expectancy, total R, drawdown, sample size, exclusions, and uncertainty.
5. Record code commit, data cutoff, market universe, configuration, and exact train/test boundaries with each result.
6. Keep live scoring, filters, Telegram behavior, and adaptive modifier unchanged until these checks pass.

## Phase 1 acceptance criteria

- [x] Inspect the 55-row Signal Auditor CSV and classify outcomes / exclusions.
- [x] Identify the 24-hour versus 72-hour horizon mismatch and enumerate records requiring re-settlement.
- [ ] Obtain original minute OHLC candles and source signal payloads for reproducible settlement.
- [ ] Resolve the two NASDAQ feed mismatches.
- [ ] Verify CADJPY settlement against the actual forward-price path and reconcile its journal state.
- [ ] Re-settle using the strict 24-hour horizon and production ordering/cost assumptions.
- [ ] Produce chronological out-of-sample baseline metrics with sample counts and uncertainty.
- [ ] Record code commit, data cutoff, market universe, configuration, and test-window boundaries.
- [x] Keep live scoring and Telegram behavior unchanged during this audit.

## Decision

**Do not tune or change the live strategy based on this first-pass sample.** The apparent positive TP1-only exit result is small (+0.096R per signal before costs) and is not yet a fair comparison under the documented 24-hour horizon. The TP2-only simplified result is approximately flat/slightly negative. Correct the settlement horizon and reproduce the price paths before evaluating strategy quality or promoting filters.


## Follow-up after Signal Auditor PR #2 — provisional 24-hour review (2026-10-13)

Signal Auditor PR #2 is merged to `main`; its default settlement horizon is now 24 hours. The 55-row CSV was re-examined against the stored signal, TP1, and terminal timestamps. Eleven records have TP1 or a recorded terminal event beyond the 24-hour cutoff. A provisional timestamp-based review is committed in Signal Auditor at `data/24h-horizon-review-provisional.csv`, with methodology and limitations in `docs/24h-horizon-reconciliation.md`.

**This is not candle-verified re-settlement.** The source repository excludes `data/candles/*.csv` from Git; the Yahoo 1-minute fetch is a rolling ~7-day window, and the earliest affected signals date from Sep 29–Oct 5. The PR test run had no candle artifact. Therefore, the original minute candles are still required before historical labels can be finalized.

### Timestamp-based provisional classes

| Class | Count |
| --- | ---: |
| TP2 | 13 |
| SL | 21 |
| TP1_THEN_SL | 5 |
| TP1_ONLY | 5 |
| NO_RESOLUTION | 9 |
| DATA_MISMATCH | 2 |
| Total | 55 |

The timestamp-based result has 44 provisionally resolved, non-mismatch records. TP1 was recorded before expiry in 23/44 (52.3%). Simplified gross fixed-R scenarios give TP1-exit +5.508R total / +0.125R per resolved trade, and TP2-only +3.343R total / +0.086R per 39 eligible records. These are **provisional calculations**, not validated live returns: they rely on stored event timestamps and target/stop distances, and do not verify minute-level coverage, price path, spreads, slippage, commissions, or partial exit handling. Do not use them to tune live strategy behavior.

### Reconciliation findings

- **NASDAQ rows 123 and 129:** Auditor and MercuryEdge both map the label `NASDAQ` to Yahoo `^IXIC`, but the recorded feed quotes (~30,924 and ~31,019) are far from signal entries (~27,313 and ~27,439). The source likely used a different Nasdaq instrument/provider. Keep both excluded; do not silently change the production mapping until the original signal source/ticker is identified.
- **CADJPY record 1223:** Signal Auditor records a SELL at 06:56:33 UTC (entry 110.86, SL 110.99) with a stop timestamp at 08:45 UTC. MercuryEdge journal has a near-identical SELL in its 06:00 UTC batch (entry 110.863998, SL 110.989818), but the timestamps differ by 56m33s and the journal snapshot remained OPEN. Treat as likely related, not confirmed identical, until publication time and archived candles are checked.
- The original `data/audit-results.csv` was deliberately left unchanged. The provisional classifications are in a separate file to prevent an unverified timestamp inference from silently rewriting canonical history.

### Remaining Phase 1 gates

- [ ] Obtain archived minute OHLC data for all 11 horizon-affected records and CADJPY, with provider/ticker and timezone provenance.
- [ ] Re-settle with the merged 24-hour engine, checking candle gaps, signal-candle exclusion, spread, same-candle ambiguity, and exact cutoff.
- [ ] Identify the actual Nasdaq instrument/source for rows 123 and 129; keep them excluded until then.
- [ ] Reconcile CADJPY source publication time, price path, and journal status.
- [ ] Recalculate final baseline after candle-level resettlement, then run chronological walk-forward comparisons. `data/walkforward.json` still has zero folds and `data/calibration.json` still has zero samples.
- [ ] Keep live scoring, filters, Telegram behavior, and adaptive modifier unchanged until out-of-sample results justify a change.
