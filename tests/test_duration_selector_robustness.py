import pandas as pd

from scripts.duration_selector_robustness import run_grid


def sample_trades():
    dates = pd.date_range("2024-01-01", periods=700, freq="D", tz="UTC")
    return pd.DataFrame({
        "scan_ts": dates,
        "symbol": ["EURUSD"] * 700,
        "direction": ["BUY"] * 700,
        "holding_period": ["SWING_24_72H"] * 700,
        "tp1_full_R_5d": [0.5 if i % 3 else -1.0 for i in range(700)],
    })


def test_sensitivity_grid_covers_stricter_sample_and_edge_thresholds(monkeypatch):
    monkeypatch.setattr("scripts.duration_selector_robustness.MIN_COUNTS", (8, 12))
    monkeypatch.setattr("scripts.duration_selector_robustness.MIN_EDGES", (0.02, 0.05))
    result, report = run_grid(sample_trades())
    assert len(result) == 4
    assert set(result["min_training_trades"]) == {8, 12}
    assert set(result["min_training_net_edge_R"]) == {0.02, 0.05}
    assert report["selection_rule_varied_without_changing_live_rules"] is True
    assert "not an independent holdout" in report["interpretation_warning"]
