"""Deterministic tests for the shared market-data normalizer and ticker resolver."""

import pandas as pd

from market_data import _normalize, resolve_ticker


def test_normalizer_returns_title_case_ohlcv_and_utc_index():
    raw = pd.DataFrame(
        {
            "open": [1.1, 1.2],
            "high": [1.15, 1.25],
            "low": [1.05, 1.15],
            "close": [1.12, 1.22],
            "volume": [100, 200],
        },
        index=pd.to_datetime(["2026-10-09 10:00", "2026-10-09 11:00"]),
    )
    result = _normalize(raw)

    assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert str(result.index.tz) == "UTC"
    assert result["Close"].tolist() == [1.12, 1.22]


def test_normalizer_handles_yfinance_multiindex_columns():
    columns = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close"], ["EURUSD=X"]],
        names=["Price", "Ticker"],
    )
    raw = pd.DataFrame(
        [[1.0, 1.2, 0.9, 1.1]],
        columns=columns,
        index=pd.to_datetime(["2026-10-09 10:00"], utc=True),
    )
    result = _normalize(raw)

    assert result is not None
    assert list(result.columns) == ["Open", "High", "Low", "Close"]
    assert float(result["Close"].iloc[0]) == 1.1


def test_normalizer_rejects_missing_ohlc_fields():
    raw = pd.DataFrame({"Open": [1.0], "Close": [1.1]})
    assert _normalize(raw) is None


def test_known_canonical_and_provider_tickers_resolve_consistently():
    cases = {
        "EURUSD": "EURUSD=X",
        "EURUSD=X": "EURUSD=X",
        "USDCAD": "CAD=X",
        "USDCHF": "CHF=X",
        "USDJPY": "JPY=X",
        "NASDAQ": "^NDX",
        "^NDX": "^NDX",
        "SPX": "^GSPC",
        "VIX": "^VIX",
        "XAUUSD": "GC=F",
        "USOIL": "CL=F",
    }
    for symbol, expected in cases.items():
        assert resolve_ticker(symbol) == expected
