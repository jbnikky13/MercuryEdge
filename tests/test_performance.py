from mercuryedge.performance import build_report


def test_performance_report_has_core_metrics():
    rows = [
        {"status": "TP2", "rr1": 1.15, "rr2": 2.25, "historical_score": 5, "crossmarket_score": 6, "crossmarket_agreement": 0.8, "direction": "BUY", "category": "forex"},
        {"status": "TP1", "rr1": 1.15, "rr2": 2.25, "historical_score": 0, "crossmarket_score": 2, "crossmarket_agreement": 0.4, "direction": "BUY", "category": "forex"},
        {"status": "SL", "rr1": 1.15, "rr2": 2.25, "historical_score": -5, "crossmarket_score": -4, "crossmarket_agreement": 0.1, "direction": "SELL", "category": "commodity"},
    ]
    report = build_report(rows)
    assert report["overall"]["resolved"] == 3
    assert report["overall"]["tp2"] == 1
    assert report["overall"]["tp1"] == 1
    assert report["overall"]["sl"] == 1
    assert report["overall"]["average_r"] is not None
    assert "historical" in report["factors"]
    assert "crossmarket" in report["factors"]
