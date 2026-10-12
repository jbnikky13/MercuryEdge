"""Read-only Yahoo Finance smoke test. Does not generate or send trading signals."""

from datetime import datetime, timezone

from market_data import get_history, resolve_ticker

# Representative instruments across FX, indices, and commodities.
SYMBOLS = ("EURUSD", "USDJPY", "NASDAQ", "XAUUSD", "USOIL")


def main() -> int:
    failures = []
    print(f"Market-data smoke test at {datetime.now(timezone.utc).isoformat()}")
    for symbol in SYMBOLS:
        ticker = resolve_ticker(symbol)
        frame = get_history(symbol, period="5d", interval="1h")
        if frame is None or frame.empty:
            failures.append(symbol)
            print(f"FAIL {symbol:10s} ticker={ticker!s:12s} no normalized candles")
            continue

        last_time = frame.index[-1]
        last_close = float(frame["Close"].iloc[-1])
        if last_close <= 0:
            failures.append(symbol)
            print(f"FAIL {symbol:10s} ticker={ticker!s:12s} invalid close={last_close}")
            continue
        print(
            f"OK   {symbol:10s} ticker={ticker!s:12s} "
            f"bars={len(frame):4d} last={last_time.isoformat()} close={last_close:.8g}"
        )

    print(f"\nResult: {len(SYMBOLS) - len(failures)}/{len(SYMBOLS)} instruments returned usable data.")
    if failures:
        print("Unavailable or invalid: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
