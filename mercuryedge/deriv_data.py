"""Read-only adapter for Deriv's public synthetic-index market data."""
from __future__ import annotations

import json
from typing import Any

import pandas as pd
import websocket

PUBLIC_WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"
SYNTHETIC_MARKETS = {"synthetic_index", "synthetic indices", "synthetic"}


class DerivAPIError(RuntimeError):
    """Raised when Deriv returns an API error or malformed response."""


class DerivPublicClient:
    """Synchronous client for unauthenticated Deriv public market data."""

    def __init__(self, url: str = PUBLIC_WS_URL, timeout: int = 15):
        self.url = url
        self.timeout = timeout

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = dict(payload)
        request_id = request.setdefault("req_id", 1)
        connection = None
        try:
            connection = websocket.create_connection(self.url, timeout=self.timeout)
            connection.send(json.dumps(request))
            while True:
                raw = connection.recv()
                if not raw:
                    raise DerivAPIError("Deriv closed the public WebSocket without a response")
                message = json.loads(raw)
                if message.get("req_id") not in (None, request_id):
                    continue
                if message.get("error"):
                    error = message["error"]
                    message_text = error.get("message", "Deriv API error") if isinstance(error, dict) else str(error)
                    raise DerivAPIError(message_text)
                return message
        except DerivAPIError:
            raise
        except Exception as exc:
            raise DerivAPIError(f"Deriv public market-data request failed: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def active_symbols(self) -> list[dict[str, Any]]:
        """Return active underlyings using the current API request schema."""
        response = self._request({"active_symbols": "full"})
        symbols = response.get("active_symbols")
        if not isinstance(symbols, list):
            raise DerivAPIError("Deriv response did not contain an active_symbols list")
        return symbols

    @staticmethod
    def symbol_code(item: dict[str, Any]) -> str:
        """Read the current field, with legacy fallback for older responses."""
        return str(item.get("underlying_symbol") or item.get("symbol") or "")

    @staticmethod
    def symbol_name(item: dict[str, Any]) -> str:
        return str(item.get("underlying_symbol_name") or item.get("display_name") or "")

    def synthetic_symbols(self) -> list[dict[str, Any]]:
        """Filter instruments using current market metadata, not display labels."""
        result = []
        for item in self.active_symbols():
            market = str(item.get("market", "")).strip().lower()
            subgroup = str(item.get("subgroup", "")).strip().lower()
            submarket = str(item.get("submarket", "")).strip().lower()
            if market in SYNTHETIC_MARKETS or subgroup in SYNTHETIC_MARKETS or submarket in SYNTHETIC_MARKETS:
                result.append(item)
        return result

    def candles(self, symbol: str, count: int = 500, granularity: int = 300) -> pd.DataFrame:
        """Fetch OHLC candles and return a UTC-indexed DataFrame."""
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        if count < 2 or count > 5000:
            raise ValueError("count must be between 2 and 5000")
        allowed = {60, 120, 180, 300, 600, 900, 1800, 3600, 7200, 14400, 28800, 86400}
        if granularity not in allowed:
            raise ValueError("unsupported candle granularity")

        response = self._request({
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "granularity": granularity,
            "style": "candles",
        })
        candles = response.get("candles")
        if not isinstance(candles, list) or not candles:
            raise DerivAPIError(f"Deriv returned no candle history for {symbol}")

        frame = pd.DataFrame(candles)
        required = {"epoch", "open", "high", "low", "close"}
        if not required.issubset(frame.columns):
            raise DerivAPIError(f"Deriv candle response for {symbol} is malformed")
        frame = frame.rename(columns={"epoch": "timestamp"})
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="s", utc=True, errors="coerce")
        for column in ("open", "high", "low", "close"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
        if frame.empty:
            raise DerivAPIError(f"Deriv returned no valid OHLC candles for {symbol}")
        invalid = (
            (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
            | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        )
        if invalid.any():
            raise DerivAPIError(f"Deriv returned invalid OHLC relationships for {symbol}")
        frame = frame.drop_duplicates(subset=["timestamp"], keep="last")
        frame = frame.set_index("timestamp").sort_index()
        frame.index.name = "timestamp"
        return frame[["open", "high", "low", "close"]]


def get_synthetic_symbols() -> list[dict[str, Any]]:
    return DerivPublicClient().synthetic_symbols()


def get_candles(symbol: str, count: int = 500, granularity: int = 300) -> pd.DataFrame:
    return DerivPublicClient().candles(symbol, count=count, granularity=granularity)


if __name__ == "__main__":
    client = DerivPublicClient()
    instruments = client.synthetic_symbols()
    print(f"Deriv synthetic instruments discovered: {len(instruments)}")
    for item in instruments:
        print(client.symbol_code(item), client.symbol_name(item), item.get("market", "?"), item.get("submarket", "?"))
