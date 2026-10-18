import subprocess
import sys
from pathlib import Path

from signal_filters import check_signal, filter_batch
from market_data import resolve_ticker, get_live_quote
from scheduler import BATCHES
from mercuryedge.config import MARKETS
from mercuryedge.__main__ import _restrict_to_batch, _signal_slot


def signal(**overrides):
    item = {
        "symbol": "EURUSD",
        "direction": "BUY",
        "entry": 1.10,\n        "atr": 0.01,
        "score": 70,
        "hit_rate": 60,
        "analogues": 80,
        "regime": "BULLISH / NORMAL",
        "confirmation": 1,
    }
    item.update(overrides)
    return item


def test_good_signal_passes_without_network():
    ok, reason = check_signal(signal())
    assert ok
    assert reason == ""


def test_weak_or_conflicting_signal_is_rejected():
    assert check_signal(signal(score=64))[0] is False
    assert check_signal(signal(hit_rate=49))[0] is False
    assert check_signal(signal(analogues=39))[0] is False
    assert check_signal(signal(confirmation=-1))[0] is False
    assert check_signal(signal(symbol="VIX", direction="SELL"))[0] is False


def test_feed_mismatch_and_missing_feed_are_rejected():
    assert check_signal(signal(), price_lookup=lambda _symbol: None)[0] is False
    assert check_signal(signal(), price_lookup=lambda _symbol: 1.20)[0] is False
    assert check_signal(signal(), price_lookup=lambda _symbol: 1.101)[0] is True


def test_filter_keeps_highest_scoring_symbol_once():
    candidates = [
        signal(score=70),
        signal(score=82, direction="SELL"),
        signal(symbol="GBPUSD", score=68),
    ]
    kept, dropped = filter_batch(candidates)
    assert [x["score"] for x in kept] == [82, 68]
    assert len(dropped) == 1
    assert dropped[0][1] == "symbol already sent today"


def test_shared_feed_uses_the_strategy_tickers():
    assert resolve_ticker("NASDAQ") == "^IXIC"
    assert resolve_ticker("^NDX") == "^NDX"
    assert resolve_ticker("USDCAD") == "CAD=X"
    assert resolve_ticker("USDCHF") == "CHF=X"
    assert resolve_ticker("EURUSD=X") == "EURUSD=X"
    assert resolve_ticker("not-a-market") is None


def test_every_configured_market_is_in_a_batch():
    configured = {market.name for market in MARKETS}
    batched = set().union(*(symbols for _, _, symbols in BATCHES))
    assert configured <= batched


def test_audit_csv_backtest_runs_from_repo_root():
    csv_path = Path(__file__).resolve().parents[1] / "audit-results.csv"
    assert csv_path.exists()
    result = subprocess.run(
        [sys.executable, "signal_filters.py", str(csv_path)],
        cwd=csv_path.parent,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "unfiltered" in result.stdout
    assert "filtered" in result.stdout


def test_batch_universe_is_applied_before_setup_ranking():
    candidates = [
        {"symbol": "EURUSD", "score": 71},
        {"symbol": "NASDAQ", "score": 99},
        {"symbol": "VIX", "score": 98},
    ]
    selected_pool = _restrict_to_batch(candidates, "morning")
    assert [item["symbol"] for item in selected_pool] == ["EURUSD"]


def test_afternoon_batch_includes_indices_and_fx():
    candidates = [
        {"symbol": "EURUSD"},
        {"symbol": "NASDAQ"},
        {"symbol": "VIX"},
        {"symbol": "UNKNOWN"},
    ]
    selected_pool = _restrict_to_batch(candidates, "afternoon")
    assert {item["symbol"] for item in selected_pool} == {
        "EURUSD", "NASDAQ", "VIX"
    }


def test_explicit_scheduled_slot_wins_over_current_clock(monkeypatch):
    monkeypatch.setenv("MERCURY_SIGNAL_SLOT", "evening")
    # A midday clock must not override the scheduled workflow identity.
    from datetime import datetime, timezone
    assert _signal_slot(datetime(2026, 10, 12, 7, 0, tzinfo=timezone.utc)) == "evening"


def test_invalid_explicit_slot_uses_clock_fallback(monkeypatch):
    monkeypatch.setenv("MERCURY_SIGNAL_SLOT", "not-a-batch")
    from datetime import datetime, timezone
    # 06:35 WAT is 05:35 UTC and falls within the morning window.
    assert _signal_slot(datetime(2026, 10, 12, 5, 35, tzinfo=timezone.utc)) == "morning"



def test_live_quote_rejects_stale_and_invalid_candles(monkeypatch):
    import pandas as pd
    import market_data
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    fresh = pd.DataFrame({"Close": [1.1]}, index=pd.DatetimeIndex([now - timedelta(minutes=5)]))
    monkeypatch.setattr(market_data, "get_candles", lambda *args, **kwargs: fresh)
    quote = get_live_quote("EURUSD")
    assert quote is not None
    assert quote["price"] == 1.1
    assert quote["age_minutes"] <= 15

    stale = pd.DataFrame({"Close": [1.1]}, index=pd.DatetimeIndex([now - timedelta(minutes=30)]))
    monkeypatch.setattr(market_data, "get_candles", lambda *args, **kwargs: stale)
    assert get_live_quote("EURUSD") is None

    invalid = pd.DataFrame({"Close": [0]}, index=pd.DatetimeIndex([now - timedelta(minutes=5)]))
    monkeypatch.setattr(market_data, "get_candles", lambda *args, **kwargs: invalid)
    assert get_live_quote("EURUSD") is None
