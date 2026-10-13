"""Fetch broad historical OHLC data and replay the current rule set without look-ahead.

Yahoo intraday history is limited; hourly bars are used for up to ~2 years and
daily bars for long context. This is research data, not a broker execution feed.
Raw downloads are intended for Actions artifacts, not commits.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from market_data import get_history
from mercuryedge.config import MARKETS
from mercuryedge.analysis import add_indicators

ROOT = Path(os.getenv("RESEARCH_OUTPUT", "research_data"))
HOURLY_PERIOD = os.getenv("RESEARCH_HOURLY_PERIOD", "2y")
DAILY_PERIOD = os.getenv("RESEARCH_DAILY_PERIOD", "10y")
HORIZON_BARS = 24


def _current_rule_signals(frame: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct the live trend-continuation/breakout rules on historical bars."""
    if frame is None or frame.empty or len(frame) < 220:
        return pd.DataFrame()
    d = add_indicators(frame)
    prev = d.shift(1)
    bullish = (d["EMA20"] > d["EMA50"]) & (d["EMA50"] > d["EMA200"]) & (d["Close"] > d["EMA20"])
    bearish = (d["EMA20"] < d["EMA50"]) & (d["EMA50"] < d["EMA200"]) & (d["Close"] < d["EMA20"])
    buy = bullish & d["RSI"].between(50, 72) & (d["MACD"] > d["MACD_SIGNAL"])
    sell = bearish & d["RSI"].between(28, 50) & (d["MACD"] < d["MACD_SIGNAL"])
    breakout = buy & (d["Close"] > d["ROLL_HIGH"]) & (prev["Close"] <= prev["ROLL_HIGH"])
    breakdown = sell & (d["Close"] < d["ROLL_LOW"]) & (prev["Close"] >= prev["ROLL_LOW"])
    direction = pd.Series("", index=d.index, dtype="object")
    direction.loc[buy] = "BUY"
    direction.loc[sell] = "SELL"
    out = d.loc[buy | sell, ["Open", "High", "Low", "Close", "ATR", "RSI"]].copy()
    out["direction"] = direction.loc[out.index]
    out["setup"] = np.where(breakout.loc[out.index], "BREAKOUT",
                    np.where(breakdown.loc[out.index], "BREAKDOWN", "TREND_CONTINUATION"))
    out["score"] = np.where(
        out["direction"].eq("BUY"),
        np.where(bullish.loc[out.index], 55, 0) + np.where(out["RSI"] > 55, 8, 0) + np.where(breakout.loc[out.index], 18, 0),
        np.where(bearish.loc[out.index], 55, 0) + np.where(out["RSI"] < 45, 8, 0) + np.where(breakdown.loc[out.index], 18, 0),
    )
    out["entry"] = out["Close"]
    out["risk"] = out["ATR"] * 1.25
    side = np.where(out["direction"].eq("BUY"), 1.0, -1.0)
    out["sl"] = out["entry"] - side * out["risk"]
    out["tp1"] = out["entry"] + side * out["risk"] * 1.15
    out["tp2"] = out["entry"] + side * out["risk"] * 2.25
    return out.dropna(subset=["entry", "risk"])


def _settle_one(signal: pd.Series, future: pd.DataFrame) -> dict:
    side = 1 if signal["direction"] == "BUY" else -1
    entry, risk = float(signal["entry"]), float(signal["risk"])
    stop, tp1, tp2 = float(signal["sl"]), float(signal["tp1"]), float(signal["tp2"])
    tp1_hit = False
    tp1_r = side * (tp1 - entry) / risk
    tp2_r = side * (tp2 - entry) / risk
    for _, candle in future.iterrows():
        high, low = float(candle["High"]), float(candle["Low"])
        stop_hit = low <= stop if side == 1 else high >= stop
        one_hit = high >= tp1 if side == 1 else low <= tp1
        two_hit = high >= tp2 if side == 1 else low <= tp2
        # Conservative tie-break: if stop and target occur in the same bar,
        # count stop first because hourly OHLC cannot reveal intrabar order.
        if stop_hit:
            return {"outcome": "TP1_THEN_SL" if tp1_hit else "SL", "tp1_hit": tp1_hit,
                    "tp1_full_R": tp1_r if tp1_hit else -1.0,
                    "tp2_full_R": -1.0,
                    "half_be_R": (0.5 * tp1_r if tp1_hit else -1.0)}
        if two_hit:
            return {"outcome": "TP2", "tp1_hit": True, "tp1_full_R": tp1_r,
                    "tp2_full_R": tp2_r, "half_be_R": 0.5 * tp1_r + 0.5 * tp2_r}
        if one_hit:
            tp1_hit = True
    last = float(future["Close"].iloc[-1]) if not future.empty else entry
    mark_r = side * (last - entry) / risk
    return {"outcome": "EXPIRED", "tp1_hit": tp1_hit,
            "tp1_full_R": tp1_r if tp1_hit else mark_r,
            "tp2_full_R": mark_r,
            "half_be_R": 0.5 * tp1_r + 0.5 * mark_r if tp1_hit else mark_r}


def replay(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    signals = _current_rule_signals(frame)
    if signals.empty:
        return pd.DataFrame()
    rows = []
    index = frame.index
    # Signals are generated only from data up to that candle; settlement uses
    # the next 24 bars, never future data in the signal features.
    for ts, signal in signals.iterrows():
        pos = index.searchsorted(ts, side="right")
        future = frame.iloc[pos:pos + HORIZON_BARS]
        if len(future) < HORIZON_BARS:
            continue
        settled = _settle_one(signal, future)
        rows.append({
            "symbol": symbol, "ts": ts.isoformat(), "direction": signal["direction"],
            "setup": signal["setup"], "score": int(signal["score"]),
            "entry": float(signal["entry"]), "sl": float(signal["sl"]),
            "tp1": float(signal["tp1"]), "tp2": float(signal["tp2"]),
            **settled,
        })
    return pd.DataFrame(rows)


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "hourly").mkdir(exist_ok=True)
    (ROOT / "daily").mkdir(exist_ok=True)
    summaries, trades, errors = [], [], []
    for market in MARKETS:
        print(f"Downloading {market.name} ({market.symbol})")
        hourly = get_history(market.symbol, period=HOURLY_PERIOD, interval="1h")
        daily = get_history(market.symbol, period=DAILY_PERIOD, interval="1d")
        if hourly is not None and not hourly.empty:
            hourly.to_csv(ROOT / "hourly" / f"{market.name}.csv", index_label="timestamp")
            replayed = replay(hourly, market.name)
            if not replayed.empty:
                trades.append(replayed)
                summaries.append({
                    "symbol": market.name, "hourly_bars": len(hourly),
                    "start_utc": hourly.index.min().isoformat(), "end_utc": hourly.index.max().isoformat(),
                    "signals": len(replayed), "tp1_hit_rate_pct": round(100 * replayed["tp1_hit"].mean(), 2),
                    "tp1_full_avg_R": round(replayed["tp1_full_R"].mean(), 4),
                    "tp2_full_avg_R": round(replayed["tp2_full_R"].mean(), 4),
                    "half_be_avg_R": round(replayed["half_be_R"].mean(), 4),
                    "costs_included": False,
                })
            else:
                summaries.append({"symbol": market.name, "hourly_bars": len(hourly),
                                  "start_utc": hourly.index.min().isoformat(),
                                  "end_utc": hourly.index.max().isoformat(), "signals": 0,
                                  "costs_included": False})
        else:
            errors.append({"symbol": market.name, "timeframe": "1h", "error": "no hourly data returned"})
        if daily is not None and not daily.empty:
            daily.to_csv(ROOT / "daily" / f"{market.name}.csv", index_label="timestamp")
        else:
            errors.append({"symbol": market.name, "timeframe": "1d", "error": "no daily data returned"})
    summary = pd.DataFrame(summaries)
    summary.to_csv(ROOT / "market-summary.csv", index=False)
    if trades:
        all_trades = pd.concat(trades, ignore_index=True)
        all_trades.to_csv(ROOT / "replayed-signals.csv", index=False)
    else:
        all_trades = pd.DataFrame()
        all_trades.to_csv(ROOT / "replayed-signals.csv", index=False)
    (ROOT / "download-errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
    report = {
        "provider": "Yahoo Finance via yfinance",
        "hourly_period_requested": HOURLY_PERIOD,
        "daily_period_requested": DAILY_PERIOD,
        "horizon_hours": HORIZON_BARS,
        "markets_configured": len(MARKETS),
        "markets_with_hourly_data": int(summary["hourly_bars"].notna().sum()) if "hourly_bars" in summary else 0,
        "replayed_signals": len(all_trades),
        "costs_included": False,
        "execution_feed_verified": False,
        "warning": "Research proxy only. Yahoo symbols may differ from broker instruments. R results exclude spread, slippage, funding and contract-specific costs. Do not enable live trading from this report alone.",
        "errors": errors,
    }
    (ROOT / "research-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if summaries else 1


if __name__ == "__main__":
    raise SystemExit(main())
