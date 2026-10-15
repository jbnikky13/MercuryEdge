import pandas as pd

from scripts.research_historical import _settle_one


def test_half_tp1_original_stop_policy_keeps_original_stop_after_tp1():
    signal = pd.Series({
        "direction": "BUY", "entry": 100.0, "risk": 10.0,
        "sl": 90.0, "tp1": 111.5, "tp2": 122.5,
    })
    candles = [{"High": 105.0, "Low": 101.0, "Close": 103.0} for _ in range(24)]
    candles[0] = {"High": 112.0, "Low": 101.0, "Close": 110.0}
    candles[1] = {"High": 108.0, "Low": 89.0, "Close": 95.0}
    result = _settle_one(signal, pd.DataFrame(candles))
    assert abs(result["half_sl_R"] - 0.075) < 1e-9
    assert abs(result["half_be_R"] - 0.575) < 1e-9


def test_exit_policy_results_are_all_reported():
    signal = pd.Series({
        "direction": "BUY", "entry": 100.0, "risk": 10.0,
        "sl": 90.0, "tp1": 111.5, "tp2": 122.5,
    })
    candles = pd.DataFrame([{"High": 105.0, "Low": 101.0, "Close": 103.0}] * 24)
    result = _settle_one(signal, candles)
    assert {"tp1_full_R", "tp2_full_R", "half_be_R", "half_sl_R"} <= result.keys()
