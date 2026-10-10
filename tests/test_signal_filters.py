from signal_filters import check_signal, filter_batch
from market_data import resolve_ticker


def signal(**overrides):
    item = {
        "symbol": "EURUSD",
        "direction": "BUY",
        "entry": 1.10,
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
    assert resolve_ticker("NASDAQ") == "^NDX"
    assert resolve_ticker("^NDX") == "^NDX"
    assert resolve_ticker("USDCAD") == "CAD=X"
    assert resolve_ticker("USDCHF") == "CHF=X"
