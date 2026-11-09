"""Read-only public market-data adapter for Deriv synthetic indices.

This module never authenticates, reads account data, or submits trades.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

import pandas as pd
import websocket

PUBLIC_WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"
SYNTHETIC_MARKET_NAMES = {"synthetic_index", "synthetic indices", "synthetic"}


class DerivAPIError(RuntimeError):
    """Raised when Deriv returns an API error or an invalid response."""


class DerivPublicClient:
    """Small synchronous client for Deriv's unauthenticated public WebSocket."""

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
                    raise DerivAPIError(
                        error.get("message", "Deriv returned an API error")
                        if isinstance(error, dict) else str(error)
                    )
                return message
        except DerivAPIError:
            raise
        except Exception as exc:
            raise DerivAPIError(f"Deriv public market-data request failed: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def active_symbols(self) -> list[dict[str, Any]]:
        """Return Deriv's currently active symbols; no account token is used."""
        response = self._request({
            "active_symbols": "full",
            "product_type": "basic",
        })
        symbols = response.get("active_symbols")
        if not isinstance(symbols, list):
            raise DerivAPIError("Deriv response did not contain an active_symbols list")
        return symbols

    def synthetic_symbols(self) -> list[dict[str, Any]]:
        """Return symbols explicitly classified as synthetic by Deriv metadata."""
        result = []
        for item in self.active_symbols():
            market = str(item.get("market", "")).strip().lower()
            market_name = str(item.get("market_display_name", "")).strip().lower()
            submarket = str(item.get("submarket", "")).strip().lower()
            submarket_name = str(item.get("submarket_display_name", "")).strip().lower()
            if (
                market in SYNTHETIC_MARKET_NAMES
                or market_name in SYNTHETIC_MARKET_NAMES
                or submarket in SYNTHETIC_MARKET_NAMES
                or submarket_name in SYNTHETIC_MARKET_NAMES
            ):
                result.append(item)
        return result

    def candles(self, symbol: str, count: int = 500, granularity: int = 300) -> pd.DataFrame:
        """Fetch historical OHLC candles, indexed by UTC timestamp."""
        if not symbol or not isinstance(symbol, str):
            raise ValueError("symbol must be a non-empty string")
        if count < 2 or count > 5000:
            raise ValueError("count must be between 2 and 5000")
        if granularity not in {60, 120, 180, 300, 600, 900, 1800, 3600, 7200, 14400, 86400}:
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
        if not isinstance(candles, list):
            raise DerivAPIError(f"Deriv returned no candle history for {symbol}")

        frame = pd.DataFrame(candles)
        required = {"epoch", "open", "high", "low", "close"}
        if frame.empty or not required.issubset(frame.columns):
            raise DerivAPIError(f"Deriv candle response for {symbol} is empty or malformed")

        frame = frame.rename(columns={"epoch": "timestamp"})
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="s", utc=True)
        for column in ("open", "high", "low", "close"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["open", "high", "low", "close"])
        frame = frame.set_index("timestamp").sort_index()
        frame.index.name = "timestamp"
        return frame[["open", "high", "low", "close"]]


def get_synthetic_symbols() -> list[dict[str, Any]]:
    """Convenience wrapper for one-shot discovery."""
    return DerivPublicClient().synthetic_symbols()


def get_candles(symbol: str, count: int = 500, granularity: int = 300) -> pd.DataFrame:
    """Convenience wrapper for one-shot candle retrieval."""
    return DerivPublicClient().candles(symbol, count=count, granularity=granularity)


if __name__ == "__main__":
    client = DerivPublicClient()
    instruments = client.synthetic_symbols()
    print(f"Deriv synthetic instruments discovered: {len(instruments)}")
    for instrument in instruments:
        print(
            instrument.get("symbol", "?"),
            instrument.get("display_name", "?"),
            instrument.get("market_display_name", instrument.get("market", "?")),
        )
