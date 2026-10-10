"""Replay candles to compare stop widths in original-risk units."""
import sys
from datetime import timedelta
import pandas as pd
from market_data import get_candles

HORIZON_H = 72
MULTS = (1.0, 1.25, 1.5, 2.0)

def simulate(sig, candles, mult):
    entry, sl, tp2 = float(sig["entry"]), float(sig["sl"]), float(sig["tp2"])
    risk = abs(entry - sl)
    sell = str(sig["direction"]).upper() == "SELL"
    sgn = -1 if sell else 1
    stop = entry - sgn * risk * mult
    tp2_r = abs(tp2 - entry) / risk
    for _, c in candles.iterrows():
        hit_stop = c["high"] >= stop if sell else c["low"] <= stop
        hit_tp = c["low"] <= tp2 if sell else c["high"] >= tp2
        if hit_stop:
            return -mult
        if hit_tp:
            return tp2_r
    last = candles["close"].iloc[-1]
    return sgn * (last - entry) / risk

def run(csv_path, candle_fn=get_candles):
    d = pd.read_csv(csv_path).drop_duplicates("id")
    d = d[d.outcome.isin(["SL", "TP2", "TP1_ONLY", "TP1_THEN_SL"])]
    rows = []
    for _, sig in d.iterrows():
        start = pd.Timestamp(sig["ts_utc"])
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
        c = candle_fn(sig["symbol"], start, start + timedelta(hours=HORIZON_H))
        if c is None or c.empty:
            continue
        c = c[c.index >= start]
        rows.append({"id": sig["id"], "symbol": sig["symbol"],
                     **{f"x{m}": simulate(sig, c, m) for m in MULTS}})
    res = pd.DataFrame(rows)
    print(f"signals tested: {len(res)} of {len(d)}")
    for m in MULTS:
        col = f"x{m}"
        stop_rate = (res[col] <= -m + 1e-9).mean() * 100 if not res.empty else float("nan")
        avg = res[col].mean() if not res.empty else float("nan")
        print(f"stop x{m:<4} avg {avg:5.2f}R  stop-out rate {stop_rate:3.0f}%")
    return res

if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "audit-results.csv")
