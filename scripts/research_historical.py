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
    strong_bull = (d["EMA20"] > d["EMA50"]) & (d["EMA50"] > d["EMA200"]) & (d["Close"] > d["EMA20"])
    strong_bear = (d["EMA20"] < d["EMA50"]) & (d["EMA50"] < d["EMA200"]) & (d["Close"] < d["EMA20"])
    bullish = strong_bull | (d["Close"] > d["EMA50"])
    bearish = strong_bear | (d["Close"] < d["EMA50"])
    buy = bullish & d["RSI"].between(50, 72) & (d["MACD"] > d["MACD_SIGNAL"])
    sell = bearish & d["RSI"].between(28, 50) & (d["MACD"] < d["MACD_SIGNAL"])
    breakout = buy & (d["Close"] > d["ROLL_HIGH"]) & (prev["Close"] <= prev["ROLL_HIGH"])
    breakdown = sell & (d["Close"] < d["ROLL_LOW"]) & (prev["Close"] >= prev["ROLL_LOW"])
    direction = pd.Series("", index=d.index, dtype="object")
    direction.loc[buy] = "BUY"
    direction.loc[sell] = "SELL"
    out = d.loc[buy | sell, ["Open", "High", "Low", "Close", "ATR", "RSI", "EMA20", "EMA50", "EMA200"]].copy()
    out["direction"] = direction.loc[out.index]
    uptrend = (out["EMA20"] > out["EMA50"]) & (out["EMA50"] > out["EMA200"])
    downtrend = (out["EMA20"] < out["EMA50"]) & (out["EMA50"] < out["EMA200"])
    out["market_regime"] = np.select([uptrend, downtrend], ["TRENDING_UP", "TRENDING_DOWN"], default="MIXED")
    atr_pct = out["ATR"] / out["Close"].replace(0, np.nan) * 100
    # Trailing median avoids using future bars to label volatility.
    rolling_median = atr_pct.rolling(120, min_periods=30).median()
    out["volatility_regime"] = np.where(atr_pct >= rolling_median, "HIGHER_VOL", "LOWER_VOL")
    out["setup"] = np.where(breakout.loc[out.index], "BREAKOUT",
                    np.where(breakdown.loc[out.index], "BREAKDOWN", "TREND_CONTINUATION"))
    base_score = np.where(
        strong_bull.loc[out.index] | strong_bear.loc[out.index], 30,
        np.where((d["Close"].loc[out.index] > d["EMA50"].loc[out.index]) |
                 (d["Close"].loc[out.index] < d["EMA50"].loc[out.index]), 18, 0)
    )
    is_buy = out["direction"].eq("BUY")
    out["score"] = (
        base_score + 25
        + np.where(is_buy & (out["RSI"] > 55), 8, 0)
        + np.where((~is_buy) & (out["RSI"] < 45), 8, 0)
        + np.where(breakout.loc[out.index] | breakdown.loc[out.index], 18, 0)
    )
    out["entry"] = out["Close"]
    out["risk"] = out["ATR"] * 1.25
    side = np.where(out["direction"].eq("BUY"), 1.0, -1.0)
    out["sl"] = out["entry"] - side * out["risk"]
    out["tp1"] = out["entry"] + side * out["risk"] * 1.15
    out["tp2"] = out["entry"] + side * out["risk"] * 2.25
    return out.dropna(subset=["entry", "risk"])


def _settle_one(signal: pd.Series, future: pd.DataFrame) -> dict:
    """Settle baseline exits and a true half-at-TP1 / half-at-breakeven policy.

    Hourly OHLC cannot reveal intrabar ordering. For the half/BE policy, if
    entry and TP2 are both touched after TP1 in one bar, assume breakeven first.
    """
    side = 1 if signal["direction"] == "BUY" else -1
    entry, risk = float(signal["entry"]), float(signal["risk"])
    stop, tp1, tp2 = float(signal["sl"]), float(signal["tp1"]), float(signal["tp2"])
    tp1_r = side * (tp1 - entry) / risk
    tp2_r = side * (tp2 - entry) / risk

    # Baseline full-position outcomes.
    tp1_hit = False
    outcome = "EXPIRED"
    last = float(future["Close"].iloc[-1]) if not future.empty else entry
    mark_r = side * (last - entry) / risk
    tp1_full_r = mark_r
    tp2_full_r = mark_r
    for _, candle in future.iterrows():
        high, low = float(candle["High"]), float(candle["Low"])
        stop_hit = low <= stop if side == 1 else high >= stop
        one_hit = high >= tp1 if side == 1 else low <= tp1
        two_hit = high >= tp2 if side == 1 else low <= tp2
        # Conservative stop-first tie-break for ambiguous hourly candles.
        if stop_hit:
            outcome = "TP1_THEN_SL" if tp1_hit else "SL"
            tp1_full_r = tp1_r if tp1_hit else -1.0
            tp2_full_r = -1.0
            break
        if two_hit:
            tp1_hit = True
            outcome = "TP2"
            tp1_full_r = tp1_r
            tp2_full_r = tp2_r
            break
        if one_hit:
            tp1_hit = True
            tp1_full_r = tp1_r

    # Independent simulation of half taken at TP1 and remaining half protected
    # by a stop at entry after TP1. This does not reuse the baseline SL state.
    half_tp1_hit = False
    half_be_r = None
    for _, candle in future.iterrows():
        high, low = float(candle["High"]), float(candle["Low"])
        original_stop_hit = low <= stop if side == 1 else high >= stop
        one_hit = high >= tp1 if side == 1 else low <= tp1
        two_hit = high >= tp2 if side == 1 else low <= tp2
        be_hit = low <= entry if side == 1 else high >= entry

        if not half_tp1_hit:
            if original_stop_hit:
                half_be_r = -1.0
                break
            if one_hit and be_hit:
                # TP1 and breakeven are both touched in this hourly candle.
                # Assume TP1 first, then the remaining half exits at entry.
                half_be_r = 0.5 * tp1_r
                break
            if two_hit:
                # A TP2 candle necessarily crosses TP1. If it also revisits
                # entry, the conservative BE-first tie-break above applies.
                half_be_r = 0.5 * tp1_r + 0.5 * tp2_r
                break
            if one_hit:
                half_tp1_hit = True
        else:
            if be_hit:
                half_be_r = 0.5 * tp1_r
                break
            if two_hit:
                half_be_r = 0.5 * tp1_r + 0.5 * tp2_r
                break

    if half_be_r is None:
        half_be_r = 0.5 * tp1_r + 0.5 * mark_r if half_tp1_hit else mark_r

    # Independent simulation: half exits at TP1; remaining half keeps original stop.
    half_tp1_hit_sl = False
    half_sl_r = None
    for _, candle in future.iterrows():
        high, low = float(candle["High"]), float(candle["Low"])
        original_stop_hit = low <= stop if side == 1 else high >= stop
        one_hit = high >= tp1 if side == 1 else low <= tp1
        two_hit = high >= tp2 if side == 1 else low <= tp2
        if not half_tp1_hit_sl:
            if original_stop_hit:
                half_sl_r = -1.0
                break
            if two_hit:
                half_sl_r = 0.5 * tp1_r + 0.5 * tp2_r
                break
            if one_hit:
                half_tp1_hit_sl = True
        else:
            if original_stop_hit:
                half_sl_r = 0.5 * tp1_r - 0.5
                break
            if two_hit:
                half_sl_r = 0.5 * tp1_r + 0.5 * tp2_r
                break
    if half_sl_r is None:
        half_sl_r = 0.5 * tp1_r + 0.5 * mark_r if half_tp1_hit_sl else mark_r

    return {
        "outcome": outcome,
        "tp1_hit": tp1_hit,
        "tp1_full_R": tp1_full_r,
        "tp2_full_R": tp2_full_r,
        "half_be_R": half_be_r,
        "half_sl_R": half_sl_r,
    }


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
            "market_regime": signal["market_regime"],
            "volatility_regime": signal["volatility_regime"],
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
