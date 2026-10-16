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
    win_rate_1d: Optional[float]
    note: str


def _features(df: pd.DataFrame) -> pd.DataFrame:
    """Create point-in-time features and forward outcomes for analogue research."""
    out = df.copy()
    out.index = pd.to_datetime(out.index, utc=True)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    close = pd.to_numeric(out["Close"], errors="coerce")
    daily_return = close.pct_change()
    out["return_1d"] = daily_return
    # Labels point FORWARD from each historical observation. They are only
    # eligible for a live query once the full label horizon has elapsed.
    out["forward_1d"] = close.shift(-1) / close - 1
    out["forward_3d"] = close.shift(-3) / close - 1
    out["forward_5d"] = close.shift(-5) / close - 1
    out["vol_20"] = daily_return.rolling(20).std()
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
    return out.replace([np.inf, -np.inf], np.nan)


def _safe_mean(series: pd.Series) -> Optional[float]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return float(clean.mean()) if len(clean) else None


def _empty_context(ts: pd.Timestamp, note: str) -> HistoricalContext:
    return HistoricalContext(
        0, 0.0, 0, ts.day_name(), ts.month, "UNKNOWN", "UNKNOWN",
        None, None, None, None, None, note,
    )


def build_context(
    df: pd.DataFrame,
    *,
    direction: str,
    timestamp,
    min_samples: int = 20,
) -> HistoricalContext:
    """Score recurring behavior using only fully matured, pre-signal outcomes.

    A historical row's 3-day forward outcome is not available until three
    daily bars after that row. This function excludes labels that would still
    be in progress at the signal timestamp, avoiding forward-label leakage.
    Calendar and regime matching is hierarchical and falls back to broader
    analogues when the narrow group is too small.
    """
    if df.empty:
        ts = pd.Timestamp(timestamp)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        return _empty_context(ts, "No historical data")

    data = _features(df)
    ts = pd.Timestamp(timestamp)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    direction = str(direction).upper()
    if direction not in {"BUY", "SELL"}:
        raise ValueError("direction must be BUY or SELL")

    # Use the latest feature state available at or before the query timestamp.
    query_day = ts.normalize()
    # Daily bars are only treated as known after their calendar day has ended.
    prior_features = data[data.index.normalize() < query_day]
    if prior_features.empty:
        return _empty_context(ts, "No prior observations")
    latest = prior_features.iloc[-1]

    # Outcomes need three complete daily bars to mature. The cutoff also
    # prevents historical forward labels from crossing into the query time.
    eligible = data[data.index.normalize() + pd.Timedelta(days=3) < query_day].dropna(
        subset=["forward_1d", "forward_3d", "forward_5d", "vol_20", "vol_median"]
    )
    if eligible.empty:
        return _empty_context(ts, "No matured forward outcomes before query time")

    day = ts.day_name()
    month = ts.month
    vol = str(latest["vol_regime"])
    trend = str(latest["trend_regime"])

    matchers = [
        (eligible["day_of_week"].eq(day) & eligible["month"].eq(month)
         & eligible["vol_regime"].eq(vol) & eligible["trend_regime"].eq(trend),
         "weekday+month+volatility+trend"),
        (eligible["day_of_week"].eq(day) & eligible["vol_regime"].eq(vol)
         & eligible["trend_regime"].eq(trend), "weekday+volatility+trend"),
        (eligible["vol_regime"].eq(vol) & eligible["trend_regime"].eq(trend),
         "volatility+trend"),
        (pd.Series(True, index=eligible.index), "all matured history"),
    ]
    sample = eligible.iloc[0:0]
    match_level = "none"
    for mask, label in matchers:
        candidate = eligible[mask]
        if len(candidate) >= min_samples:
            sample, match_level = candidate, label
            break
    if sample.empty:
        return _empty_context(ts, "Insufficient matured historical analogues")

    sign = 1 if direction == "BUY" else -1
    signed_1d = sample["forward_1d"] * sign
    signed_3d = sample["forward_3d"] * sign
    signed_5d = sample["forward_5d"] * sign
    win_rate = float((signed_3d > 0).mean())
    win_rate_1d = float((signed_1d > 0).mean())
    mean_3d = float(signed_3d.mean())

    # Blend hit-rate edge and normalized forward-return edge, then shrink
    # toward neutral for small samples and weak effects. This is a score
    # modifier, not a probability forecast or proof of profitability.
    hit_edge = (win_rate - 0.5) * 2.0
    scale = float(sample["forward_3d"].abs().median())
    return_edge = float(np.tanh(mean_3d / scale)) if scale > 1e-12 else 0.0
    raw_edge = 0.65 * hit_edge + 0.35 * return_edge
    sample_confidence = min(1.0, len(sample) / 100.0)
    confidence = abs(raw_edge) * sample_confidence
    score = int(np.clip(round(raw_edge * 12 * sample_confidence), -8, 8))

    note = (
        f"{len(sample)} matured analogues ({match_level}); "
        f"3D forward directional hit rate={win_rate * 100:.1f}%; "
        f"mean signed 3D forward return={mean_3d * 100:.3f}%"
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
        avg_3d_return=mean_3d,
        avg_5d_return=_safe_mean(signed_5d),
        win_rate_3d=win_rate,
        win_rate_1d=win_rate_1d,
        note=note,
    )
