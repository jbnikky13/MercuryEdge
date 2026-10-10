"""Compare stop widths against post-signal candles; never infer a winner without data.

Run: python stop_width_test.py audit-results.csv
Uses the shared market_data provider. If candles are unavailable, reports that
explicitly rather than crashing or claiming a best stop width.
"""
import sys
from datetime import timedelta

import pandas as pd

from market_data import get_candles

HORIZON_H = 72
MULTS = (1.0, 1.25, 1.5, 2.0)


def _column(frame, name):
    """Accept lower-case or title-case columns from either provider version."""
    if name in frame.columns:
        return frame[name]
    title = name.title()
    if title in frame.columns:
        return frame[title]
    raise KeyError(f"candle data is missing {name!r}/{title!r}")


def simulate(sig, candles, mult):
    entry, sl, tp2 = float(sig["entry"]), float(sig["sl"]), float(sig["tp2"])
    risk = abs(entry - sl)
    if risk <= 0:
        raise ValueError("stop width must be greater than zero")
    sell = str(sig["direction"]).upper() == "SELL"
    sgn = -1 if sell else 1
    stop = entry - sgn * risk * mult
    tp2_r = abs(tp2 - entry) / risk
    highs, lows = _column(candles, "high"), _column(candles, "low")
    for high, low in zip(highs, lows):
        # Conservative assumption when both levels are touched in one candle.
        hit_stop = high >= stop if sell else low <= stop
        hit_tp = low <= tp2 if sell else high >= tp2
        if hit_stop:
            return -mult
        if hit_tp:
            return tp2_r
    last = float(_column(candles, "close").iloc[-1])
    return sgn * (last - entry) / risk


def run(csv_path, candle_fn=get_candles):
    d = pd.read_csv(csv_path).drop_duplicates("id")
    d = d[d.outcome.isin(["SL", "TP2", "TP1_ONLY", "TP1_THEN_SL"])]
    rows = []
    for _, sig in d.iterrows():
        start = pd.Timestamp(sig["ts_utc"])
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
        candles = candle_fn(
            sig["symbol"], start.to_pydatetime(),
            (start + timedelta(hours=HORIZON_H)).to_pydatetime(), interval="5m",
        )
        if candles is None or candles.empty:
            continue
        candles = candles[candles.index >= start]
        if candles.empty:
            continue
        rows.append({
            "id": sig["id"], "symbol": sig["symbol"],
            **{f"x{m}": simulate(sig, candles, m) for m in MULTS},
        })

    columns = ["id", "symbol"] + [f"x{m}" for m in MULTS]
    res = pd.DataFrame(rows, columns=columns)
    print(f"signals tested: {len(res)} of {len(d)}")
    if res.empty:
        print("No stop width can be ranked: the shared market-data feed returned no usable post-signal candles.")
        print("Check Yahoo availability, ticker mappings, and the 5-minute candle window, then rerun.")
        return res

    for m in MULTS:
        col = f"x{m}"
        stop_rate = (res[col] <= -m + 1e-9).mean() * 100
        print(f"stop x{m:<4} avg {res[col].mean():5.2f}R  stop-out rate {stop_rate:3.0f}%")
    return res


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "audit-results.csv")
