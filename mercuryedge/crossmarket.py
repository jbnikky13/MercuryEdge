from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CrossMarketContext:
    score: int
    confidence: float
    agreement: float
    observations: int
    relationships: tuple[str, ...]
    note: str


# These are hypotheses, not permanent rules. The engine measures the current
# rolling relationship before applying any directional modifier.
RELATIONSHIPS = {
    "XAUUSD": {"DXY": -1, "VIX": 1},
    "XAGUSD": {"DXY": -1, "VIX": 1},
    "USOIL": {"DXY": -1, "USDCAD": -1},
    "UKOIL": {"DXY": -1, "USDCAD": -1},
    "COPPER": {"DXY": -1, "AUDUSD": 1},
    "AUDUSD": {"COPPER": 1, "USOIL": 1, "DXY": -1},
    "USDCAD": {"USOIL": -1, "DXY": 1},
    "EURUSD": {"DXY": -1},
    "GBPUSD": {"DXY": -1},
    "NZDUSD": {"DXY": -1},
    "USDJPY": {"DXY": 1, "VIX": -1},
    "USDCHF": {"DXY": 1, "VIX": 1},
    "SPX": {"VIX": -1, "DXY": -1},
    "NASDAQ": {"VIX": -1, "DXY": -1},
    "DJI": {"VIX": -1, "DXY": -1},
    "RUSSELL2000": {"VIX": -1, "DXY": -1},
}


def _returns(frame: pd.DataFrame) -> pd.Series:
    if frame.empty or "Close" not in frame:
        return pd.Series(dtype=float)
    close = pd.to_numeric(frame["Close"], errors="coerce")
    return close.pct_change().dropna()


def _correlation(a: pd.Series, b: pd.Series, window: int) -> float | None:
    joined = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna().tail(window)
    if len(joined) < max(30, window // 2):
        return None
    value = joined["a"].corr(joined["b"])
    return float(value) if np.isfinite(value) else None


def build_context(
    target_name: str,
    direction: str,
    market_frames: Mapping[str, pd.DataFrame],
    *,
    window: int = 60,
    min_correlation: float = 0.15,
) -> CrossMarketContext:
    relationships = RELATIONSHIPS.get(target_name, {})
    if not relationships:
        return CrossMarketContext(0, 0.0, 0.0, 0, (), "No cross-market model for this instrument")

    target = _returns(market_frames.get(target_name, pd.DataFrame()))
    if target.empty:
        return CrossMarketContext(0, 0.0, 0.0, 0, (), "Target return series unavailable")

    sign = 1 if direction == "BUY" else -1
    evidence = []
    labels = []

    for related_name, expected_sign in relationships.items():
        related = _returns(market_frames.get(related_name, pd.DataFrame()))
        corr = _correlation(target, related, window)
        if corr is None or abs(corr) < min_correlation:
            continue

        # Recent direction of the related market, weighted by the observed
        # rolling correlation rather than blindly trusting the hypothesis.
        recent = related.tail(3).mean()
        if not np.isfinite(recent) or recent == 0:
            continue

        observed_effect = np.sign(recent) * np.sign(corr)
        expected_effect = np.sign(expected_sign) * sign
        agreement = float(observed_effect == expected_effect)

        # Stronger correlations contribute more, but each relationship is capped.
        evidence.append((agreement - 0.5) * min(abs(corr), 0.8))
        labels.append(f"{related_name}:{corr:+.2f}")

    if not evidence:
        return CrossMarketContext(0, 0.0, 0.0, 0, (), "No statistically useful cross-market evidence")

    raw = float(np.mean(evidence))
    score = int(round(np.clip(raw * 24, -8, 8)))
    agreement = float(np.mean([1.0 if x > 0 else 0.0 for x in evidence]))
    confidence = float(min(1.0, len(evidence) / 3.0) * min(1.0, abs(raw) / 0.25))

    return CrossMarketContext(
        score=score,
        confidence=round(confidence, 3),
        agreement=round(agreement, 3),
        observations=len(evidence),
        relationships=tuple(labels),
        note=f"{len(evidence)} adaptive relationships; rolling window={window}",
    )
