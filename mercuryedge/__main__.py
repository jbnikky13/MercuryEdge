from __future__ import annotations

import logging

from .analysis import add_indicators, analyze
from .calendar import trading_status
from .config import MARKETS, MAX_SETUPS
from .data import load_market
from .journal import record_signal
from .signal import format_signal, send_telegram

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> None:
    allowed, reason = trading_status()
    if not allowed:
        logging.info("MercuryEdge scan skipped: %s", reason)
        return

    candidates = []
    for market in MARKETS:
        logging.info("Scanning %s", market.name)
        df = load_market(market.symbol)
        if df.empty:
            continue
        enriched = add_indicators(df)
        result = analyze(enriched)
        if result:
            candidates.append((market, result))

    candidates.sort(key=lambda item: item[1]["score"], reverse=True)
    selected = candidates[:MAX_SETUPS]

    print("\nMERCURYEDGE SCAN")
    print(f"Markets scanned: {len(MARKETS)}")
    print(f"Setups found: {len(candidates)}")
    print(f"Publishing: {len(selected)}")
    print("=​" * 60)

    if not selected:
        print("No qualifying setups right now.")
        return

    for market, setup in selected:
        record_signal(market, setup)
        message = format_signal(market.name, market.category, setup)
        print(message)
        print("=" * 60)
        try:
            send_telegram(message)
        except Exception as exc:
            logging.warning("Telegram delivery failed: %s", exc)


if __name__ == "__main__":
    main()
