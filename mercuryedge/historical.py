from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class HistoricalContext:
    score: int
    confidence: float
    sample_size: int
    day_of_week: str
    month: int
    volatility_regime: str
    trend_regime: str
    avg_1d_return: Optional[float]
    avg_3d_return: Optional[float]
    avg_5d_return: Optional[float]
    win_rate_3d: Optional[float]
    note: str


def _features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.index = pd.to_datetime(out.index, utc=True)
    out = out.sort_index()
    close = out["Close"].astype(float)
    ret = close.pct_change()
    out["return_1d"] = ret
    out["return_3d"] = close.pct_change(3)
    out["return_5d"] = close.pct_change(5)
    out["vol_20"] = ret.rolling(20).std()
    out["vol_median"] = out["vol_20"].rolling(60).median()
    out["vol_regime"] = np.where(
        out["vol_20"] > out["vol_median"] * 1.25,
        "HIGH",
        np.where(out["vol_20"] < out["vol_median"] * 0.75, "LOW", "NORMAL"),
    )
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    out["trend_regime"] = np.where(
        (close > ema20) & (ema20 > ema50),
        "BULLISH",
        np.where((close < ema20) & (ema20 < ema50), "BEARISH", "RANGE"),
    )
    out["day_of_week"] = out.index.day_name()
    out["month"] = out.index.month
    return out.dropna(subset=["return_3d", "return_5d", "vol_20", "vol_median"])


def _safe_mean(series: pd.Series) -> Optional[float]:
    return float(series.mean()) if len(series) else None


def build_context(df: pd.DataFrame, *, direction: str, timestamp, min_samples: int = 20) -> HistoricalContext:
    """Measure recurring historical behavior without assuming a fixed pattern."""
    if df.empty:
        return HistoricalContext(0, 0.0, 0, "", 0, "UNKNOWN", "UNKNOWN", None, None, None, None, "No historical data")

    data = _features(df)
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    prior = data[data.index < ts]
    if prior.empty:
        return HistoricalContext(0, 0.0, 0, ts.day_name(), ts.month, "UNKNOWN", "UNKNOWN",
                                 None, None, None, None, "No prior observations")

    latest = prior.iloc[-1]
    day = ts.day_name()
    month = ts.month
    vol = str(latest["vol_regime"])
    trend = str(latest["trend_regime"])

    sample = prior[
        (prior["day_of_week"] == day)
        & (prior["month"] == month)
        & (prior["vol_regime"] == vol)
        & (prior["trend_regime"] == trend)
    ]
    if len(sample) < min_samples:
        sample = prior[
            (prior["day_of_week"] == day)
            & (prior["vol_regime"] == vol)
            & (prior["trend_regime"] == trend)
        ]
    if len(sample) < min_samples:
        sample = prior[(prior["vol_regime"] == vol) & (prior["trend_regime"] == trend)]
    if len(sample) < min_samples:
        sample = prior.tail(min(len(prior), 252))

    sign = 1 if direction == "BUY" else -1
    signed_1d = sample["return_1d"] * sign
    signed_3d = sample["return_3d"] * sign
    signed_5d = sample["return_5d"] * sign
    win_rate = float((signed_3d > 0).mean()) if len(sample) else None

    if len(sample) < 20 or win_rate is None:
        score = 0
        confidence = 0.0
    else:
        edge = (win_rate - 0.5) * 2.0
        sample_conf = min(1.0, len(sample) / 100.0)
        confidence = abs(edge) * sample_conf
        score = int(round(edge * 12 * sample_conf))
        score = max(-12, min(12, score))

    note = (
        f"{len(sample)} historical analogues; 3D directional hit rate={win_rate * 100:.1f}%"
        if win_rate is not None
        else "Insufficient historical analogues"
    )
    return HistoricalContext(
        score=score,
        confidence=round(float(confidence), 3),
        sample_size=int(len(sample)),
        day_of_week=day,
        month=month,
        volatility_regime=vol,
        trend_regime=trend,
        avg_1d_return=_safe_mean(signed_1d),
        avg_3d_return=_safe_mean(signed_3d),
        avg_5d_return=_safe_mean(signed_5d),
        win_rate_3d=win_rate,
        note=note,
    )
