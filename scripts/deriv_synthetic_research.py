"""Research-only Deriv synthetic backtest using MercuryEdge's existing rules.

This script never sends Telegram messages or places trades. Results are exploratory:
Deriv history availability, assumed costs, and out-of-sample validation must be
reviewed before any strategy or signal integration is considered.
"""
from __future__ import annotations

import argparse
from collections import Counter

import pandas as pd

from mercuryedge.analysis import add_indicators
from mercuryedge.backtest import backtest
from mercuryedge.deriv_data import DerivPublicClient

DEFAULT_SYMBOLS = ("R_10", "R_25", "R_50", "R_75", "R_100")


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only Deriv synthetic strategy audit")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--count", type=int, default=5000)
    parser.add_argument("--granularity", type=int, default=3600, help="Candle interval in seconds (default: 1 hour)")
    parser.add_argument("--horizon", type=int, default=24, help="Forward candles evaluated per setup")
    args = parser.parse_args()

    client = DerivPublicClient(timeout=25)
    available = {client.symbol_code(item): item for item in client.synthetic_symbols()}
    requested = [value.strip() for value in args.symbols.split(",") if value.strip()]
    unknown = [symbol for symbol in requested if symbol not in available]
    if unknown:
        parser.error(f"Symbols are not currently classified as active Deriv synthetics: {', '.join(unknown)}")

    print("MERCURYEDGE DERIV SYNTHETIC RESEARCH — NOT LIVE SIGNALS")
    print(f"Granularity: {args.granularity}s | Requested candles: {args.count} | Horizon: {args.horizon}")
    print("No Telegram delivery, order placement, or production pipeline integration.")
    print("-" * 72)

    total = Counter()
    for symbol in requested:
        raw = client.candles(symbol, count=args.count, granularity=args.granularity)
        frame = raw.rename(columns={
            "open": "Open", "high": "High", "low": "Low", "close": "Close"
        })
        frame["Volume"] = 0.0
        frame = frame[["Open", "High", "Low", "Close", "Volume"]].dropna()
        if len(frame) < 250:
            print(f"{symbol}: SKIPPED — only {len(frame)} usable candles (need at least 250)")
            continue

        outcomes = backtest(frame, warmup=220, horizon=args.horizon)
        counts = Counter(outcomes)
        total.update(counts)
        resolved = counts["TP1"] + counts["TP2"] + counts["SL"]
        wins = counts["TP1"] + counts["TP2"]
        rate = wins / resolved * 100 if resolved else 0.0
        print(
            f"{symbol}: candles={len(frame)} setups={len(outcomes)} "
            f"resolved={resolved} TP1={counts['TP1']} TP2={counts['TP2']} "
            f"SL={counts['SL']} unresolved={counts['UNRESOLVED']} "
            f"resolved_win_rate={rate:.1f}%"
        )

    resolved = total["TP1"] + total["TP2"] + total["SL"]
    wins = total["TP1"] + total["TP2"]
    rate = wins / resolved * 100 if resolved else 0.0
    print("-" * 72)
    print(
        f"AGGREGATE: setups={sum(total.values())} resolved={resolved} "
        f"TP1={total['TP1']} TP2={total['TP2']} SL={total['SL']} "
        f"unresolved={total['UNRESOLVED']} resolved_win_rate={rate:.1f}%"
    )
    print("Interpretation: exploratory historical replay only; not evidence of profitability.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
