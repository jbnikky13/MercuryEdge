from __future__ import annotations

import argparse
from collections import Counter

from .analysis import add_indicators, analyze
from .config import MARKETS
from .data import load_market


def evaluate_setup(enriched, index: int, setup: dict, horizon: int = 24) -> str:
    """Evaluate forward candles without look-ahead leakage.

    If TP and SL occur in the same candle, SL wins. This conservative rule
    avoids overstating historical performance when intrabar ordering is unknown.
    """
    future = enriched.iloc[index + 1 : index + 1 + horizon]
    if future.empty:
        return "UNRESOLVED"

    for _, candle in future.iterrows():
        if setup["direction"] == "BUY":
            hit_sl = candle.Low <= setup["sl"]
            hit_tp2 = candle.High >= setup["tp2"]
            hit_tp1 = candle.High >= setup["tp1"]
        else:
            hit_sl = candle.High >= setup["sl"]
            hit_tp2 = candle.Low <= setup["tp2"]
            hit_tp1 = candle.Low <= setup["tp1"]

        if hit_sl:
            return "SL"
        if hit_tp2:
            return "TP2"
        if hit_tp1:
            return "TP1"

    return "UNRESOLVED"


def backtest(df, warmup: int = 220, horizon: int = 24):
    enriched = add_indicators(df)
    outcomes = []
    for index in range(warmup, len(enriched) - 1):
        setup = analyze(enriched.iloc[: index + 1])
        if not setup:
            continue
        outcomes.append(evaluate_setup(enriched, index, setup, horizon))
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser(description="MercuryEdge historical signal audit")
    parser.add_argument("--horizon", type=int, default=24, help="Forward candles to evaluate")
    args = parser.parse_args()

    all_outcomes = []
    print("\nMERCURYEDGE BACKTEST")
    print(f"Forward horizon: {args.horizon} candles")
    print("=" * 60)

    for market in MARKETS:
        df = load_market(market.symbol)
        if df.empty:
            continue
        outcomes = backtest(df, horizon=args.horizon)
        all_outcomes.extend(outcomes)
        counts = Counter(outcomes)
        resolved = counts["TP1"] + counts["TP2"] + counts["SL"]
        wins = counts["TP1"] + counts["TP2"]
        win_rate = (wins / resolved * 100) if resolved else 0
        print(f"{market.name:8} signals={len(outcomes):4} resolved={resolved:4} win_rate={win_rate:5.1f}%")

    counts = Counter(all_outcomes)
    resolved = counts["TP1"] + counts["TP2"] + counts["SL"]
    wins = counts["TP1"] + counts["TP2"]
    win_rate = (wins / resolved * 100) if resolved else 0
    print("=" * 60)
    print(f"TOTAL signals={len(all_outcomes)} resolved={resolved} win_rate={win_rate:.1f}%")
    print(dict(counts))


if __name__ == "__main__":
    main()
