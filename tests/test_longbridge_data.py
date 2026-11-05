from datetime import datetime, timezone

from mercuryedge.longbridge_data import configured_symbols, fetch_quotes, normalize_quote


class FakeQuote:
    symbol = "NVDA.US"
    last_done = "200.13"
    prev_close_price = "206.69"
    open = "203.50"
    high = "206.79"
    low = "199.68"
    volume = 123456
    turnover = "1234567.89"
    trade_session = "Pre"
    trade_status = "Normal"


def test_configured_symbols_deduplicates_and_normalizes(monkeypatch):
    monkeypatch.setenv("MERCURY_LONGBRIDGE_SYMBOLS", " nvda.us, AAPL.US,NVDA.US ,,")
    assert configured_symbols() == ["NVDA.US", "AAPL.US"]


def test_normalize_quote_marks_observation_time_not_exchange_time():
    observed = datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc)
    result = normalize_quote(FakeQuote(), observed_at=observed)

    assert result["symbol"] == "NVDA.US"
    assert result["last"] == "200.13"
    assert result["previous_close"] == "206.69"
    assert result["volume"] == 123456
    assert result["observed_at_utc"] == "2026-11-05T14:00:00+00:00"
    assert "not exchange event time" in result["timestamp_type"]
    assert result["source"] == "Longbridge OpenAPI"


def test_fetch_quotes_is_disabled_without_symbols(monkeypatch):
    monkeypatch.delenv("MERCURY_LONGBRIDGE_SYMBOLS", raising=False)
    monkeypatch.delenv("LONGBRIDGE_OAUTH_CLIENT_ID", raising=False)
    assert fetch_quotes() == []


def test_fetch_quotes_fails_closed_without_client_id(monkeypatch):
    monkeypatch.setenv("MERCURY_LONGBRIDGE_SYMBOLS", "NVDA.US")
    monkeypatch.delenv("LONGBRIDGE_OAUTH_CLIENT_ID", raising=False)
    assert fetch_quotes() == []
