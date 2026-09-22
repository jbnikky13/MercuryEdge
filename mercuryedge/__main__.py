from __future__ import annotations

import logging

from .analysis import add_indicators, analyze
from .calendar import trading_status
from .config import MARKETS, MAX_SETUPS
from .data import load_historical, load_market
from .historical import build_context
from .journal import record_signal
from .news import nfp_risk, should_reduce_risk
from .signal import format_signal, send_telegram

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> None:
    allowed, reason = trading_status()
    if not allowed:
        logging.info("MercuryEdge scan skipped: %s", reason)
        return

    news = nfp_risk()
    if news.high_impact:
        logging.info("News risk detected: %s", news.reason)

    candidates = []
    historical_loaded = 0

    for market in MARKETS:
        logging.info("Scanning %s", market.name)
        df = load_market(market.symbol)
        if df.empty:
            continue

        enriched = add_indicators(df)
        base = analyze(enriched)
        if not base:
            continue

        # Historical research is a modifier, not a standalone signal.
        history = load_historical(market.symbol)
        context = build_context(
            history,
            direction=base["direction"],
            timestamp=enriched.index[-1],
        ) if not history.empty else None
        if context:
            historical_loaded += 1

        result = analyze(enriched, context)
        if not result:
            continue

        if should_reduce_risk(market.category, news):
            result["score"] = max(0, result["score"] - 8)
            result["news_risk"] = news.label

        candidates.append((market, result))

    candidates.sort(key=lambda item: item[1]["score"], reverse=True)
    selected = candidates[:MAX_SETUPS]

    print("\nMERCURYEDGE HISTORICAL INTELLIGENCE SCAN")
    print(f"Markets scanned: {len(MARKETS)}")
    print(f"Historical profiles loaded: {historical_loaded}")
    print(f"Setups found: {len(candidates)}")
    print(f"Publishing: {len(selected)}")
    print(f"News: {news.label}")
    print("=" * 70)

    if not selected:
        print("No qualifying setups right now.")
        return

    for market, setup in selected:
        record_signal(market, setup, news)
        message = format_signal(market.name, market.category, setup)
        print(message)
        print("=" * 70)
        try:
            send_telegram(message)
        except Exception as exc:
            logging.warning("Telegram delivery failed: %s", exc)


if __name__ == "__main__":
    main()
