# Directional Intelligence (research / paper mode)

This upgrade adds auditable BUY/SELL geometry checks, confirmed M/W reversal-breakout
diagnostics, and per-symbol/per-direction matured outcome summaries.

## Safety contract

- No signal is automatically reversed.
- A confirmed M/W pattern is advisory in this first release. It is not yet a live
  veto because the current market feed is hourly and the user's screenshots are M1;
  those timeframes must not be conflated.
- Outcome learning uses only resolved TP1/TP2/SL outcomes. Mixed TP1-then-SL,
  unresolved, and data-mismatch rows are excluded from the binary rate.
- A direction with fewer than 30 resolved outcomes remains OBSERVE. A low Wilson
  95% lower bound after 30+ outcomes is REVIEW only, not an automatic trade block.
- Main remains paper/research only pending walk-forward and broker/demo parity checks.

## M/W definition

A swing pivot is not considered confirmed until three bars have elapsed to its right.
A W requires two comparable confirmed lows, an intervening neckline and a close above
the neckline plus an ATR buffer. An M is the inverse. This is intentionally stricter
than visual pattern labelling and avoids using a pattern before its breakout confirms.

## Evidence limitations

The supplied 77-row audit is a small mixed-symbol sample. It is useful for diagnostics,
not enough to fit a dependable predictive model or claim profitability. In particular,
a price move after signal publication does not prove the opposite direction was
tradable at the original entry. Counterfactual evaluation must use identical timestamps,
risk distances, costs and chronological train/test splits.
