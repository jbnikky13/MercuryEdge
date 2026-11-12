import pandas as pd

from scripts.deriv_paper_monitor import (
    LEDGER_COLUMNS, build_report, update_ledger,
)
from scripts.deriv_strategy_lab_v2 import HOLDOUT_START


def _frame(n=700):
    idx = pd.date_range("2026-10-10", periods=n, freq="h", tz="UTC")
    close = pd.Series(range(n), index=idx, dtype=float) + 100
    return pd.DataFrame({"Open": close - .2, "High": close + .5,
                         "Low": close - .5, "Close": close})


def test_empty_ledger_report_is_shadow_only_and_never_eligible():
    report = build_report(pd.DataFrame(columns=LEDGER_COLUMNS), "2026-11-09T07:00:00+00:00")
    assert report["signals_recorded"] == 0
    assert report["paper_eligible"] is False
    assert report["orders_placed"] is False


def test_ledger_columns_are_stable_and_holdout_cutoff_is_respected(monkeypatch):
    import scripts.deriv_paper_monitor as monitor

    monkeypatch.setattr(monitor, "_direction", lambda strategy, row, prev: "BUY")
    ledger = pd.DataFrame(columns=LEDGER_COLUMNS)
    # Start far enough back for indicator warm-up and extend beyond the frozen cutoff.
    result = update_ledger({"R_10": _frame(800)}, ledger)
    assert list(result.columns) == LEDGER_COLUMNS
    assert not result.empty
    assert (pd.to_datetime(result.signal_time, utc=True) > HOLDOUT_START).all()


def test_report_counts_open_and_closed_without_claiming_live_execution():
    ledger = pd.DataFrame([{
        "trade_id": "x", "strategy": "regime_pullback", "symbol": "R_10",
        "signal_time": "2026-11-09T00:00:00+00:00",
        "entry_time": "2026-11-09T01:00:00+00:00", "direction": "BUY",
        "regime": "TREND", "vol_regime": "NORMAL", "entry": 100,
        "risk_points": 1, "stop": 99, "target": 101.6, "status": "OPEN",
        "closed_time": "", "gross_R": "", "net_R_1x_min_spread": "",
        "net_R_1_5x_min_spread": "", "net_R_2x_min_spread": "",
    }])
    report = build_report(ledger, "2026-11-09T02:00:00+00:00")
    assert report["open_signals"] == 1
    assert report["closed_signals"] == 0
    assert report["paper_eligible"] is False



def _report_trade(trade_id, strategy, symbol, entry_time, closed_time, status, net=1.0):
    return {
        "trade_id": trade_id, "strategy": strategy, "symbol": symbol,
        "signal_time": entry_time, "entry_time": entry_time,
        "direction": "BUY", "regime": "TREND", "vol_regime": "NORMAL",
        "entry": 100, "risk_points": 1, "stop": 99, "target": 101.6,
        "status": status, "closed_time": closed_time, "gross_R": net,
        "net_R_1x_min_spread": net, "net_R_1_5x_min_spread": net,
        "net_R_2x_min_spread": net,
    }


def test_report_includes_strategy_with_only_open_trades():
    ledger = pd.DataFrame([_report_trade(
        "open-only", "regime_pullback", "R_100",
        "2026-11-11T09:00:00+00:00", "", "OPEN",
    )])
    report = build_report(ledger, "2026-11-12T00:00:00+00:00")
    group = report["strategy_symbol_results"][0]
    assert group["strategy"] == "regime_pullback"
    assert group["symbol"] == "R_100"
    assert group["open_trades"] == 1
    assert group["closed_trades"] == 0
    assert group["1x_min_spread"]["trades"] == 0


def test_overlapping_trades_are_retained_but_not_counted_as_independent():
    ledger = pd.DataFrame([
        _report_trade("first", "regime_breakout", "R_50",
                      "2026-11-08T18:00:00+00:00", "2026-11-09T17:00:00+00:00",
                      "CLOSED", 1.6),
        _report_trade("overlap", "regime_breakout", "R_50",
                      "2026-11-08T19:00:00+00:00", "2026-11-09T18:00:00+00:00",
                      "CLOSED", -1.0),
        _report_trade("separate", "regime_breakout", "R_50",
                      "2026-11-09T18:00:00+00:00", "2026-11-10T17:00:00+00:00",
                      "CLOSED", 1.6),
    ])
    report = build_report(ledger, "2026-11-11T00:00:00+00:00")
    group = report["strategy_symbol_results"][0]
    assert group["closed_trades"] == 3
    assert group["1x_min_spread"]["trades"] == 3
    assert group["1x_min_spread_independent_only"]["trades"] == 2
    assert group["independent_signals"] == 2
    assert group["overlapping_signals"] == 1
    assert report["paper_eligible"] is False
