import pandas as pd

from scripts.analyze_independent_research import analyze, select_non_overlapping


def test_select_non_overlapping_skips_same_symbol_signals_within_24_hours():
    trades = pd.DataFrame([
        {"symbol": "EURUSD", "ts": "2026-01-01T00:00:00Z", "tp1_full_R": 1.0, "tp2_full_R": 1.5, "half_be_R": 0.5, "half_sl_R": 0.4},
        {"symbol": "EURUSD", "ts": "2026-01-01T23:00:00Z", "tp1_full_R": -1.0, "tp2_full_R": -1.0, "half_be_R": -1.0, "half_sl_R": -1.0},
        {"symbol": "EURUSD", "ts": "2026-01-02T00:00:00Z", "tp1_full_R": 1.0, "tp2_full_R": 1.5, "half_be_R": 0.5, "half_sl_R": 0.4},
        {"symbol": "GBPUSD", "ts": "2026-01-01T01:00:00Z", "tp1_full_R": -1.0, "tp2_full_R": -1.0, "half_be_R": -1.0, "half_sl_R": -1.0},
    ])
    selected = select_non_overlapping(trades)
    assert len(selected) == 3
    assert list(selected.loc[selected["symbol"] == "EURUSD", "ts"].dt.hour) == [0, 0]


def test_cost_sensitivity_never_improves_average_return():
    trades = pd.DataFrame([
        {"symbol": "EURUSD", "ts": "2026-01-01T00:00:00Z", "tp1_full_R": 1.0, "tp2_full_R": 1.5, "half_be_R": 0.5, "half_sl_R": 0.4},
        {"symbol": "GBPUSD", "ts": "2026-01-01T01:00:00Z", "tp1_full_R": -1.0, "tp2_full_R": -1.0, "half_be_R": -1.0, "half_sl_R": -1.0},
    ])
    _, summary, _, _, _ = analyze(trades)
    tp1 = summary[summary["policy"] == "tp1_full_R"].sort_values("assumed_round_trip_cost_R")
    assert tp1["mean_R"].is_monotonic_decreasing
    assert tp1.iloc[0]["trades"] == tp1.iloc[-1]["trades"]


def test_independent_analysis_reports_chronological_periods():
    trades = pd.DataFrame([
        {"symbol": f"S{i}", "ts": f"2026-01-0{i+1}T00:00:00Z", "tp1_full_R": 0.5, "tp2_full_R": 1.0, "half_be_R": 0.25, "half_sl_R": 0.2}
        for i in range(4)
    ])
    _, _, _, periods, _ = analyze(trades)
    assert periods["chronological_period"].nunique() == 4
