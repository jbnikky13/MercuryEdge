from __future__ import annotations

import logging

from .analysis import add_indicators, analyze
from .calendar import trading_status
from .config import MARKETS, MAX_SETUPS
from .crossmarket import build_context as build_crossmarket_context
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
    market_data = {}
    market_history = {}
    historical_loaded = 0

    # Load the market universe once so relationships can be evaluated jointly.
    for market in MARKETS:
        logging.info("Loading %s", market.name)
        frame = load_market(market.symbol)
        if not frame.empty:
            market_data[market.name] = frame

        history = load_historical(market.symbol)
        if not history.empty:
            market_history[market.name] = history

    for market in MARKETS:
        df = market_data.get(market.name)
        if df is None or df.empty:
            continue

        enriched = add_indicators(df)
        base = analyze(enriched)
        if not base:
            continue

        history = market_history.get(market.name)
        context = (
            build_context(
                history,
                direction=base["direction"],
                timestamp=enriched.index[-1],
            )
            if history is not None and not history.empty
            else None
        )
        if context:
            historical_loaded += 1

        result = analyze(enriched, context)
        if not result:
            continue

        crossmarket = build_crossmarket_context(
            market.name,
            result["direction"],
            market_data,
        )
        result["crossmarket_score"] = crossmarket.score
        result["crossmarket_confidence"] = crossmarket.confidence
        result["crossmarket_agreement"] = crossmarket.agreement
        result["crossmarket_observations"] = crossmarket.observations
        result["crossmarket_relationships"] = crossmarket.relationships
        result["crossmarket_note"] = crossmarket.note

        # Cross-market evidence is intentionally bounded. It confirms or
        # challenges a technical setup; it cannot create a setup by itself.
        result["score"] = int(max(0, min(100, result["score"] + crossmarket.score)))

        if should_reduce_risk(market.category, news):
            result["score"] = max(0, result["score"] - 8)
            result["news_risk"] = news.label

        candidates.append((market, result))

    candidates.sort(key=lambda item: item[1]["score"], reverse=True)
    selected = candidates[:MAX_SETUPS]

    print("\nMERCURYEDGE MARKET INTELLIGENCE SCAN")
    print(f"Markets loaded: {len(market_data)}/{len(MARKETS)}")
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
