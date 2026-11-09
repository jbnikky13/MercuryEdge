"""Live, read-only smoke test for Deriv public synthetic market data."""
from __future__ import annotations

from mercuryedge.deriv_data import DerivPublicClient, DerivAPIError


def main() -> int:
    client = DerivPublicClient(timeout=20)
    instruments = client.synthetic_symbols()
    if not instruments:
        raise DerivAPIError("No synthetic instruments were returned by Deriv active_symbols")

    print(f"DISCOVERED_SYNTHETICS={len(instruments)}")
    for item in instruments:
        print(
            "SYMBOL",
            client.symbol_code(item),
            "|",
            client.symbol_name(item),
            "| market=",
            item.get("market", ""),
            "| submarket=",
            item.get("submarket", ""),
        )

    tested = 0
    for item in instruments[:3]:
        symbol = client.symbol_code(item)
        if not symbol:
            continue
        frame = client.candles(symbol, count=20, granularity=300)
        if len(frame) < 2:
            raise DerivAPIError(f"Insufficient candles returned for {symbol}: {len(frame)}")
        if not frame.index.is_monotonic_increasing or frame.index.tz is None:
            raise DerivAPIError(f"Timestamp validation failed for {symbol}")
        print(
            f"CANDLES_OK symbol={symbol} rows={len(frame)} "
            f"first={frame.index[0].isoformat()} last={frame.index[-1].isoformat()} "
            f"last_close={frame['close'].iloc[-1]}"
        )
        tested += 1

    if tested == 0:
        raise DerivAPIError("Synthetic instruments were listed but none had a usable symbol code")
    print(f"DERIV_PUBLIC_SMOKE_TEST=PASS instruments={len(instruments)} candle_symbols_tested={tested}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
