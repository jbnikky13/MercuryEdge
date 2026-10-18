import pandas as pd

from scripts.analyze_entry_stretch import analyze


def test_entry_stretch_analysis_compares_buckets_and_fixed_caps():
    frame = pd.DataFrame({
        "scan_ts": pd.date_range("2026-01-01", periods=6, freq="D", tz="UTC"),
        "symbol": ["EURUSD", "EURUSD", "GBPUSD", "GBPUSD", "XAUUSD", "XAUUSD"],
        "entry_stretch_atr": [0.2, 0.8, 1.2, 1.8, 2.1, 2.8],
        "tp1_full_R_24h": [1.15, -1.0, 1.15, -1.0, -1.0, 1.15],
    })
    buckets, caps, report = analyze(frame)
    assert len(buckets) == 20
    assert len(caps) == 12
    assert report["eligible_rows"] == 6
    assert report["live_filter_changed"] is False
    row = caps[(caps.max_entry_stretch_atr == 1.5) & (caps.assumed_cost_R == 0.1)].iloc[0]
    assert row["selected_trades"] == 3
    assert row["excluded_trades"] == 3


def test_entry_stretch_analysis_drops_invalid_measurements():
    frame = pd.DataFrame({
        "scan_ts": ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"],
        "symbol": ["EURUSD", "GBPUSD"],
        "entry_stretch_atr": [0.4, None],
        "tp1_full_R_24h": [1.15, -1.0],
    })
    _, _, report = analyze(frame)
    assert report["eligible_rows"] == 1
    assert report["missing_or_invalid_stretch_or_outcome_rows"] == 1
