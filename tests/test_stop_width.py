import pandas as pd

from stop_width_test import run, simulate


def test_stop_width_simulation_accepts_shared_title_case_columns():
    signal = {"entry": 100.0, "sl": 98.0, "tp2": 104.0, "direction": "BUY"}
    candles = pd.DataFrame(
        {"High": [104.5], "Low": [99.0], "Close": [104.2]},
        index=pd.to_datetime(["2026-10-01T10:00:00Z"]),
    )
    assert simulate(signal, candles, 1.0) == 2.0


def test_stop_width_test_handles_no_candle_data(tmp_path):
    csv_path = tmp_path / "audit.csv"
    pd.DataFrame([{
        "id": 1,
        "ts_utc": "2026-10-01T10:00:00+00:00",
        "symbol": "EURUSD",
        "direction": "BUY",
        "entry": 1.1,
        "sl": 1.09,
        "tp2": 1.122,
        "outcome": "SL",
    }]).to_csv(csv_path, index=False)

    result = run(str(csv_path), candle_fn=lambda *args, **kwargs: None)
    assert result.empty
    assert "x1.0" in result.columns
