from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

OUTCOMES_PATH = Path("data/outcomes.jsonl")
MIN_DIRECTIONAL_SAMPLES = 30


def _normalise_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data.columns = [str(column).lower() for column in data.columns]
    required = {"open", "high", "low", "close"}
    if not required.issubset(data.columns):
        raise ValueError(f"OHLC data missing: {sorted(required - set(data.columns))}")
    return data.sort_index()


def detect_mw_pattern(
    frame: pd.DataFrame,
    *,
    lookback: int = 90,
    pivot_width: int = 3,
    tolerance_atr: float = 0.35,
    neckline_buffer_atr: float = 0.10,
) -> dict:
    """Detect only confirmed double-top/bottom breakouts using closed input bars.

    A pivot is usable only after pivot_width bars have printed to its right.
    This deliberately favours precision over early pattern guesses and avoids
    using an unfinished swing point as if it were confirmed.
    """
    data = _normalise_ohlc(frame).tail(max(lookback, pivot_width * 2 + 8))
    if len(data) < pivot_width * 2 + 8:
        return {"pattern": "NONE", "bias": None, "confirmed": False, "reason": "insufficient_bars"}

    high = data["high"].to_numpy(dtype=float)
    low = data["low"].to_numpy(dtype=float)
    close = data["close"].to_numpy(dtype=float)
    previous_close = np.r_[close[0], close[:-1]]
    tr = np.maximum(high - low, np.maximum(np.abs(high - previous_close), np.abs(low - previous_close)))
    atr_value = float(pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
    if not math.isfinite(atr_value) or atr_value <= 0:
        return {"pattern": "NONE", "bias": None, "confirmed": False, "reason": "invalid_atr"}

    highs, lows = [], []
    last_confirmable = len(data) - pivot_width
    for index in range(pivot_width, last_confirmable):
        left = slice(index - pivot_width, index)
        right = slice(index + 1, index + pivot_width + 1)
        if high[index] >= np.max(high[left]) and high[index] > np.max(high[right]):
            highs.append((index, high[index]))
        if low[index] <= np.min(low[left]) and low[index] < np.min(low[right]):
            lows.append((index, low[index]))

    # W: two comparable confirmed lows with a meaningful intervening peak,
    # followed by a close above that peak (neckline).
    if len(lows) >= 2:
        (i1, p1), (i2, p2) = lows[-2:]
        if i2 > i1 and i2 - i1 >= pivot_width * 2:
            between = high[i1 + 1:i2]
            neckline = float(np.max(between)) if len(between) else float("nan")
            similar = abs(p1 - p2) <= tolerance_atr * atr_value
            separated = neckline - max(p1, p2) >= 0.5 * atr_value
            if similar and separated and close[-1] > neckline + neckline_buffer_atr * atr_value:
                return {
                    "pattern": "W", "bias": "BUY", "confirmed": True,
                    "neckline": neckline, "swing_1": float(p1), "swing_2": float(p2),
                    "atr": atr_value, "reason": "confirmed_neckline_breakout",
                }

    # M: two comparable confirmed highs with a meaningful intervening trough,
    # followed by a close below that trough (neckline).
    if len(highs) >= 2:
        (i1, p1), (i2, p2) = highs[-2:]
        if i2 > i1 and i2 - i1 >= pivot_width * 2:
            between = low[i1 + 1:i2]
            neckline = float(np.min(between)) if len(between) else float("nan")
            similar = abs(p1 - p2) <= tolerance_atr * atr_value
            separated = min(p1, p2) - neckline >= 0.5 * atr_value
            if similar and separated and close[-1] < neckline - neckline_buffer_atr * atr_value:
                return {
                    "pattern": "M", "bias": "SELL", "confirmed": True,
                    "neckline": neckline, "swing_1": float(p1), "swing_2": float(p2),
                    "atr": atr_value, "reason": "confirmed_neckline_breakdown",
                }

    return {"pattern": "NONE", "bias": None, "confirmed": False, "reason": "no_confirmed_breakout"}


def validate_directional_levels(setup: dict) -> tuple[bool, str | None]:
    """Catch BUY/SELL labels paired with geometrically inverted SL/TP levels."""
    try:
        entry, stop = float(setup["entry"]), float(setup["sl"])
        tp1, tp2 = float(setup["tp1"]), float(setup["tp2"])
        direction = str(setup["direction"]).upper()
    except (KeyError, TypeError, ValueError):
        return False, "missing_or_invalid_directional_levels"
    values = (entry, stop, tp1, tp2)
    if not all(math.isfinite(value) for value in values):
        return False, "non_finite_directional_levels"
    if direction == "BUY" and not (stop < entry < tp1 <= tp2):
        return False, "BUY requires SL < entry < TP1 <= TP2"
    if direction == "SELL" and not (tp2 <= tp1 < entry < stop):
        return False, "SELL requires TP2 <= TP1 < entry < SL"
    if direction not in {"BUY", "SELL"}:
        return False, "unknown_direction"
    return True, None


def directional_outcome_profile(
    rows: list[dict],
    *,
    min_samples: int = MIN_DIRECTIONAL_SAMPLES,
) -> dict:
    """Summarise matured directional outcomes; never infer a reversal from one loss.

    TP2 and TP1_ONLY count as positive; SL as negative. TP1_THEN_SL is mixed
    and excluded from the binary rate. Data mismatches/unresolved rows are excluded.
    """
    grouped: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for row in rows:
        status = str(row.get("status", row.get("outcome", ""))).upper()
        symbol = str(row.get("symbol", row.get("market", ""))).upper()
        direction = str(row.get("direction", "")).upper()
        if not symbol or direction not in {"BUY", "SELL"}:
            continue
        if status in {"TP1", "TP1_ONLY", "TP2", "WIN"}:
            grouped[(symbol, direction)].append(True)
        elif status in {"SL", "LOSS"}:
            grouped[(symbol, direction)].append(False)

    report = {}
    for (symbol, direction), outcomes in grouped.items():
        n = len(outcomes)
        wins = sum(outcomes)
        rate = wins / n if n else 0.0
        # Wilson lower confidence bound (95%); only sufficiently sampled,
        # persistently weak directions can be considered for a later gate.
        z = 1.96
        denominator = 1 + z * z / n
        centre = rate + z * z / (2 * n)
        margin = z * math.sqrt((rate * (1 - rate) + z * z / (4 * n)) / n)
        lower = (centre - margin) / denominator
        report[f"{symbol}:{direction}"] = {
            "samples": n, "wins": wins, "win_rate": round(rate, 4),
            "wilson_95_lower": round(lower, 4),
            "eligible_for_review": n >= min_samples,
            # This is deliberately advisory until walk-forward approval exists.
            "action": "REVIEW" if n >= min_samples and lower < 0.40 else "OBSERVE",
        }
    return report


def load_matured_outcomes(
    path: Path = OUTCOMES_PATH,
    audit_csv: Path = Path("audit-results.csv"),
) -> list[dict]:
    """Load resolver outcomes plus the supplied historical audit snapshot.

    Deduplicate on symbol/direction/timestamp where possible. CSV rows marked
    mixed, unresolved, or data-mismatch remain present for traceability but are
    excluded by directional_outcome_profile from binary win-rate estimation.
    """
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    seen = {
        (
            str(row.get("symbol", row.get("market", ""))).upper(),
            str(row.get("direction", "")).upper(),
            str(row.get("signal_time", row.get("ts_utc", ""))),
        )
        for row in rows
    }
    if audit_csv.exists():
        try:
            audit = pd.read_csv(audit_csv)
            for record in audit.to_dict("records"):
                key = (
                    str(record.get("symbol", "")).upper(),
                    str(record.get("direction", "")).upper(),
                    str(record.get("signal_time", record.get("ts_utc", ""))),
                )
                if key in seen:
                    continue
                rows.append({
                    "symbol": record.get("symbol"),
                    "direction": record.get("direction"),
                    "status": record.get("outcome"),
                    "signal_time": record.get("ts_utc"),
                    "source": "audit-results.csv",
                })
                seen.add(key)
        except (OSError, ValueError, pd.errors.ParserError):
            pass
    return rows


def assess_direction(symbol: str, setup: dict, frame: pd.DataFrame, outcomes: list[dict] | None = None) -> dict:
    """Return auditable pattern, outcome and direction/level integrity diagnostics."""
    levels_ok, levels_reason = validate_directional_levels(setup)
    pattern = detect_mw_pattern(frame)
    direction = str(setup.get("direction", "")).upper()
    conflict = bool(pattern["confirmed"] and pattern["bias"] != direction)
    profile = directional_outcome_profile(outcomes if outcomes is not None else load_matured_outcomes())
    learned = profile.get(f"{str(symbol).upper()}:{direction}", {
        "samples": 0, "wins": 0, "win_rate": None, "wilson_95_lower": None,
        "eligible_for_review": False, "action": "OBSERVE",
    })
    return {
        "direction_integrity_ok": levels_ok,
        "direction_integrity_reason": levels_reason,
        "mw_pattern": pattern["pattern"],
        "mw_pattern_bias": pattern["bias"],
        "mw_pattern_confirmed": pattern["confirmed"],
        "mw_pattern_conflict": conflict,
        "mw_pattern_reason": pattern["reason"],
        "directional_outcome_samples": learned["samples"],
        "directional_outcome_win_rate": learned["win_rate"],
        "directional_outcome_action": learned["action"],
        "directional_learning_advisory": True,
    }
