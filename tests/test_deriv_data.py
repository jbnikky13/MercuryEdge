import json

import pytest

from mercuryedge.deriv_data import DerivAPIError, DerivPublicClient


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.sent = None
        self.closed = False

    def send(self, payload):
        self.sent = json.loads(payload)

    def recv(self):
        return json.dumps(self.response)

    def close(self):
        self.closed = True


def test_active_symbols_uses_current_public_request_schema(monkeypatch):
    fake = FakeConnection({"req_id": 1, "active_symbols": [
        {"underlying_symbol": "R_100", "market": "synthetic_index"}
    ]})
    monkeypatch.setattr("mercuryedge.deriv_data.websocket.create_connection", lambda *a, **k: fake)
    result = DerivPublicClient().active_symbols()
    assert result[0]["underlying_symbol"] == "R_100"
    assert fake.sent == {"active_symbols": "full", "req_id": 1}
    assert "authorize" not in fake.sent
    assert fake.closed


def test_current_and_legacy_symbol_field_helpers():
    assert DerivPublicClient.symbol_code({"underlying_symbol": "R_100"}) == "R_100"
    assert DerivPublicClient.symbol_code({"symbol": "R_50"}) == "R_50"
    assert DerivPublicClient.symbol_name({"underlying_symbol_name": "Volatility 100"}) == "Volatility 100"


def test_synthetic_symbols_filters_using_current_market_metadata(monkeypatch):
    client = DerivPublicClient()
    monkeypatch.setattr(client, "active_symbols", lambda: [
        {"underlying_symbol": "R_100", "market": "synthetic_index", "submarket": "random_index"},
        {"underlying_symbol": "frxEURUSD", "market": "forex", "submarket": "major"},
    ])
    assert [item["underlying_symbol"] for item in client.synthetic_symbols()] == ["R_100"]


def test_candles_are_normalized_to_utc_ohlc(monkeypatch):
    fake = FakeConnection({"req_id": 1, "candles": [
        {"epoch": 1_800_000_000, "open": "100", "high": "102", "low": "99", "close": "101"}
    ]})
    monkeypatch.setattr("mercuryedge.deriv_data.websocket.create_connection", lambda *a, **k: fake)
    frame = DerivPublicClient().candles("R_100", count=10, granularity=300)
    assert list(frame.columns) == ["open", "high", "low", "close"]
    assert str(frame.index.tz) == "UTC"
    assert frame.iloc[0]["close"] == 101.0
    assert fake.sent["style"] == "candles"


def test_api_errors_are_raised(monkeypatch):
    fake = FakeConnection({"req_id": 1, "error": {"message": "Invalid symbol"}})
    monkeypatch.setattr("mercuryedge.deriv_data.websocket.create_connection", lambda *a, **k: fake)
    with pytest.raises(DerivAPIError, match="Invalid symbol"):
        DerivPublicClient().active_symbols()


def test_invalid_ohlc_relationship_is_rejected(monkeypatch):
    fake = FakeConnection({"req_id": 1, "candles": [
        {"epoch": 1_800_000_000, "open": "100", "high": "98", "low": "99", "close": "101"}
    ]})
    monkeypatch.setattr("mercuryedge.deriv_data.websocket.create_connection", lambda *a, **k: fake)
    with pytest.raises(DerivAPIError, match="invalid OHLC"):
        DerivPublicClient().candles("R_100", count=10, granularity=300)


@pytest.mark.parametrize("count,granularity", [(1, 300), (5001, 300), (10, 30)])
def test_invalid_candle_parameters_are_rejected(count, granularity):
    with pytest.raises(ValueError):
        DerivPublicClient().candles("R_100", count=count, granularity=granularity)
