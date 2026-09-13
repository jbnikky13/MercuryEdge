from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_OHLC = ("Open", "High", "Low", "Close")


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    value = 100 - (100 / (1 + rs))
    value = value.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    value = value.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    value = value.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    return value


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev_close).abs(), (df["Low"] - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def macd(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    fast = ema(series, 12)
    slow = ema(series, 26)
    line = fast - slow
    signal = ema(line, 9)
    return line, signal, line - signal


def _validate_ohlc(df: pd.DataFrame) -> None:
    if not isinstance(df, pd.DataFrame):
        raise TypeError("market data must be a pandas DataFrame")
    missing = [column for column in REQUIRED_OHLC if column not in df.columns]
    if missing:
        raise ValueError(f"market data missing required columns: {', '.join(missing)}")
    if df.empty:
        raise ValueError("market data is empty")
    for column in REQUIRED_OHLC:
        if not pd.api.types.is_numeric_dtype(df[column]):
            raise ValueError(f"market data column {column} must be numeric")


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    _validate_ohlc(df)
    out = df.copy()
    out["EMA20"] = ema(out["Close"], 20)
    out["EMA50"] = ema(out["Close"], 50)
    out["EMA200"] = ema(out["Close"], 200)
    out["RSI"] = rsi(out["Close"])
    out["ATR"] = atr(out)
    out["MACD"], out["MACD_SIGNAL"], out["MACD_HIST"] = macd(out["Close"])
    out["ROLL_HIGH"] = out["High"].rolling(20).max().shift(1)
    out["ROLL_LOW"] = out["Low"].rolling(20).min().shift(1)
    return out.dropna()


def _trend(row: pd.Series) -> tuple[str, int]:
    bullish = row.EMA20 > row.EMA50 > row.EMA200 and row.Close > row.EMA20
    bearish = row.EMA20 < row.EMA50 < row.EMA200 and row.Close < row.EMA20
    if bullish:
        return "BULLISH", 30
    if bearish:
        return "BEARISH", 30
    if row.Close > row.EMA50:
        return "BULLISH", 18
    if row.Close < row.EMA50:
        return "BEARISH", 18
    return "NEUTRAL", 0


def analyze(df: pd.DataFrame) -> dict | None:
    if len(df) < 220:
        return None
    required = ("EMA20", "EMA50", "EMA200", "RSI", "ATR", "MACD", "MACD_SIGNAL", "ROLL_HIGH", "ROLL_LOW")
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"indicator data missing required columns: {', '.join(missing)}")
    row = df.iloc[-1]
    previous = df.iloc[-2]
    trend, score = _trend(row)
    direction = None
    setup = None
    if trend == "BULLISH" and row.RSI >= 50 and row.RSI <= 72 and row.MACD > row.MACD_SIGNAL:
        direction, setup, score = "BUY", "TREND CONTINUATION", score + 25
    elif trend == "BEARISH" and row.RSI >= 28 and row.RSI <= 50 and row.MACD < row.MACD_SIGNAL:
        direction, setup, score = "SELL", "TREND CONTINUATION", score + 25
    if direction == "BUY" and row.Close > row.ROLL_HIGH and previous.Close <= previous.ROLL_HIGH:
        setup, score = "BREAKOUT", score + 18
    elif direction == "SELL" and row.Close < row.ROLL_LOW and previous.Close >= previous.ROLL_LOW:
        setup, score = "BREAKDOWN", score + 18
    if direction == "BUY" and row.RSI > 55:
        score += 8
    elif direction == "SELL" and row.RSI < 45:
        score += 8
    if direction is None or not np.isfinite(row.ATR) or row.ATR <= 0:
        return None
    entry = float(row.Close)
    stop_distance = float(row.ATR) * 1.25
    if direction == "BUY":
        stop, tp1, tp2 = entry - stop_distance, entry + stop_distance * 1.15, entry + stop_distance * 2.25
    else:
        stop, tp1, tp2 = entry + stop_distance, entry - stop_distance * 1.15, entry - stop_distance * 2.25
    return {"direction": direction, "setup": setup, "trend": trend, "score": int(min(100, score)), "entry": entry, "tp1": float(tp1), "tp2": float(tp2), "sl": float(stop), "rr1": 1.15, "rr2": 2.25, "rsi": float(row.RSI), "atr": float(row.ATR), "timestamp": str(df.index[-1])}
