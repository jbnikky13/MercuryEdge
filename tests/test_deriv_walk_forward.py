import pandas as pd

import scripts.deriv_walk_forward as research


def test_build_trade_rows_uses_only_matured_forward_windows(monkeypatch):
    index = pd.date_range("2025-01-01", periods=230, freq="h", tz="UTC")
    frame = pd.DataFrame({
        "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0,
        "Volume": 0.0,
    }, index=index)
    monkeypatch.setattr(research, "add_indicators", lambda data: data.copy())
    monkeypatch.setattr(
        research,
        "analyze",
        lambda history: {
            "direction": "BUY", "entry": 100.0, "sl": 99.0,
            "tp1": 101.15, "tp2": 102.25,
        },
    )
    monkeypatch.setattr(
        research,
        "_settle_one",
        lambda setup, future: {
            "outcome": "SL", "tp1_full_R": -1.0, "tp2_full_R": -1.0,
        },
    )

    rows = research.build_trade_rows(frame, "R_75", horizon=5, warmup=220)

    assert len(rows) == 5
    assert rows["symbol"].eq("R_75").all()
    assert rows["direction"].eq("BUY").all()
    assert rows["tp1_full_R"].eq(-1.0).all()
    assert rows["ts"].iloc[-1] == index[224].isoformat()


def test_build_trade_rows_rejects_invalid_horizon():
    frame = pd.DataFrame()
    try:
        research.build_trade_rows(frame, "R_75", horizon=0)
    except ValueError as exc:
        assert "horizon" in str(exc)
    else:
        raise AssertionError("Expected invalid horizon to raise ValueError")
