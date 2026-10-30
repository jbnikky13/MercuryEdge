import numpy as np
import pandas as pd

from mercuryedge.directional import (
    assess_direction, detect_mw_pattern, directional_outcome_profile,
    validate_directional_levels,
)


def _frame(close):
    close = np.asarray(close, dtype=float)
    idx = pd.date_range("2026-01-01", periods=len(close), freq="h", tz="UTC")
    return pd.DataFrame({
        "Open": close, "High": close + 0.15, "Low": close - 0.15, "Close": close,
    }, index=idx)


def test_directional_levels_reject_inverted_sell_geometry():
    good = {"direction": "SELL", "entry": 10, "sl": 11, "tp1": 9, "tp2": 8}
    bad = {"direction": "SELL", "entry": 10, "sl": 9, "tp1": 11, "tp2": 12}
    assert validate_directional_levels(good) == (True, None)
    assert validate_directional_levels(bad)[0] is False


def test_directional_levels_reject_inverted_buy_geometry():
    good = {"direction": "BUY", "entry": 10, "sl": 9, "tp1": 11, "tp2": 12}
    bad = {"direction": "BUY", "entry": 10, "sl": 11, "tp1": 9, "tp2": 8}
    assert validate_directional_levels(good) == (True, None)
    assert validate_directional_levels(bad)[0] is False


def test_outcome_profile_is_direction_and_symbol_specific():
    rows = [{"symbol": "EURCHF", "direction": "SELL", "status": "SL"} for _ in range(25)]
    rows += [{"symbol": "EURCHF", "direction": "BUY", "status": "TP2"} for _ in range(25)]
    report = directional_outcome_profile(rows, min_samples=20)
    assert report["EURCHF:SELL"]["win_rate"] == 0
    assert report["EURCHF:SELL"]["action"] == "REVIEW"
    assert report["EURCHF:BUY"]["win_rate"] == 1
    assert report["EURCHF:BUY"]["action"] == "OBSERVE"


def test_mw_detector_never_confirms_on_insufficient_history():
    result = detect_mw_pattern(_frame([1, 2, 1, 2, 1]))
    assert result["confirmed"] is False
    assert result["pattern"] == "NONE"


def test_confirmed_w_pattern_requires_neckline_breakout():
    result = detect_mw_pattern(_frame([10, 9, 8, 7, 8, 9, 10, 9, 8, 7.02, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]))
    assert result["pattern"] == "W"
    assert result["bias"] == "BUY"
    assert result["confirmed"] is True


def test_confirmed_m_pattern_requires_neckline_breakdown():
    result = detect_mw_pattern(_frame([10, 11, 12, 13, 12, 11, 10, 11, 12, 12.98, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3]))
    assert result["pattern"] == "M"
    assert result["bias"] == "SELL"
    assert result["confirmed"] is True


def test_assessment_flags_conflicting_confirmed_pattern_and_bad_levels():
    # The assessment is diagnostic; it never silently flips a trade direction.
    frame = _frame(np.linspace(1.0, 1.2, 120))
    setup = {"direction": "SELL", "entry": 1.2, "sl": 1.1, "tp1": 1.3, "tp2": 1.4}
    result = assess_direction("EURCHF", setup, frame, outcomes=[])
    assert result["direction_integrity_ok"] is False
    assert result["directional_learning_advisory"] is True
    assert result["mw_pattern"] in {"NONE", "W", "M"}
