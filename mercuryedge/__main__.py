from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from .analysis import adaptive_modifiers, add_indicators, analyze
from .calendar import WAT, trading_status
from .config import (
    MARKETS,
    MAX_CURRENCY_EXPOSURE,
    MAX_SETUPS,
    MIN_ADX,
    REQUIRE_HTF_TREND,
    SIGNAL_HORIZON_HOURS,
)
from .crossmarket import build_context as build_crossmarket_context
from .data import load_historical, load_market
from .historical import build_context
from .journal import read_journal, record_signal
from .news import nfp_risk, should_reduce_risk
from .signal import format_bulletin, send_telegram
from .upgrades import build_features, select_setups
from signal_filters import filter_batch
from market_data import get_live_price
from scheduler import BATCHES

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def _signal_slot(now_utc: datetime | None = None) -> str:
    """Return the signal window using Nigeria WAT, not runner/UTC time."""
    now = (now_utc or datetime.now(timezone.utc)).astimezone(WAT)
    minutes = now.hour * 60 + now.minute
    for name, (hour, minute), _symbols in BATCHES:
        if hour * 60 + minute <= minutes < hour * 60 + minute + 20:
            return name.lower()
    slots = [(h * 60 + m, name.lower()) for name, (h, m), _ in BATCHES]
    due = [slot for slot in slots if slot[0] <= minutes]
    return max(due)[1] if due else "overnight"


def _restrict_to_batch(candidates: list[dict], slot: str) -> list[dict]:
    """Restrict the candidate pool before ranking/capping, so other sessions
    cannot crowd valid setups out of the active batch.
    """
    batch_name = slot.upper()
    symbols = next(
        (symbols for name, _time, symbols in BATCHES if name == batch_name),
        set(),
    )
    return [item for item in candidates if item.get("symbol") in symbols]


def _open_signals(horizon_hours: int = 24) -> list[dict]:
    """Only treat recent OPEN journal rows as exposure already on the book."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=horizon_hours)
    active = []
    for row in read_journal():
        if row.get("status") != "OPEN":
            continue
        try:
            ts = pd.Timestamp(row["signal_time"])
            ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        except (KeyError, TypeError, ValueError):
            continue
        if ts.to_pydatetime() >= cutoff:
            active.append(row)
    return active


def main() -> None:
    slot = _signal_slot()
    # Overnight and pre-London batches target FX/commodities, so don't gate them
    # on the US cash-session calendar. Afternoon/evening retain the US-market guard.
    if slot in {"overnight", "morning"}:
        now_local = datetime.now(WAT)
        if now_local.weekday() >= 5:
            logging.info("MercuryEdge batch skipped: local weekend")
            return
    else:
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
            market.name, result["direction"], market_data
        )
        result["crossmarket_score"] = crossmarket.score
        result["crossmarket_confidence"] = crossmarket.confidence
        result["crossmarket_agreement"] = crossmarket.agreement
        result["crossmarket_observations"] = crossmarket.observations
        result["crossmarket_relationships"] = crossmarket.relationships
        result["crossmarket_note"] = crossmarket.note

        adaptive = adaptive_modifiers(
            result.get("historical_score", 0),
            crossmarket.score,
            crossmarket.agreement,
        )
        result["adaptive_enabled"] = adaptive["enabled"]
        result["adaptive_historical_modifier"] = adaptive["historical"]
        result["adaptive_crossmarket_modifier"] = adaptive["crossmarket"]
        result["adaptive_agreement_modifier"] = adaptive["agreement"]

        result["score"] = int(
            max(
                0,
                min(
                    100,
                    result["score"]
                    + crossmarket.score
                    + adaptive["historical"]
                    + adaptive["crossmarket"]
                    + adaptive["agreement"],
                ),
            )
        )

        if should_reduce_risk(market.category, news):
            result["score"] = max(0, result["score"] - 8)
            result["news_risk"] = news.label

        # The upgrade layer receives the market's canonical display symbol
        # (EURUSD, XAUUSD, USOIL, etc.) so currency exposure is interpretable.
        candidates.append(
            {
                "symbol": market.name,
                "direction": result["direction"],
                "score": result["score"],
                "_market": market,
                "_setup": result,
                "_frame": df,
            }
        )

    # Restrict before ranking and MAX_SETUPS so off-session markets cannot
    # consume the slots and then be discarded afterward.
    batch_candidates = _restrict_to_batch(candidates, slot)
    open_signals = _open_signals(SIGNAL_HORIZON_HOURS)
    selected_candidates, skipped = select_setups(
        batch_candidates,
        market_data,
        max_setups=MAX_SETUPS,
        existing=open_signals,
        min_adx=MIN_ADX,
        require_htf=REQUIRE_HTF_TREND,
        max_per_ccy=MAX_CURRENCY_EXPOSURE,
    )

    # Avoid re-sending symbols from the recent journal within the scheduler's 12h window.
    now_utc = datetime.now(timezone.utc)
    recent_symbols = {}
    for row in read_journal():
        try:
            sent_at = pd.Timestamp(row.get("signal_time"))
            sent_at = sent_at.tz_localize("UTC") if sent_at.tzinfo is None else sent_at.tz_convert("UTC")
            if now_utc - sent_at.to_pydatetime() < timedelta(hours=12):
                recent_symbols[row.get("market") or row.get("symbol")] = 1
        except (TypeError, ValueError):
            continue
    # Audit quality gate: block weak, paused, repeated, or feed-mismatched setups.
    filter_candidates = []
    candidate_by_key = {}
    for item in selected_candidates:
        setup = item["_setup"]
        rate = setup.get("historical_win_rate_3d")
        filter_sig = {
            "symbol": item["symbol"], "direction": item["direction"],
            "entry": setup.get("entry"), "score": setup.get("score"),
            "hit_rate": float(rate) * 100 if rate is not None else None,
            "analogues": setup.get("historical_samples"),
            "regime": setup.get("historical_regime"),
            "confirmation": setup.get("crossmarket_score", 0),
            "tp1": setup.get("tp1"), "tp2": setup.get("tp2"), "sl": setup.get("sl"),
        }
        filter_candidates.append(filter_sig)
        candidate_by_key[(item["symbol"], item["direction"])] = item
    kept, dropped = filter_batch(filter_candidates, price_lookup=get_live_price, already_sent_today=recent_symbols)
    selected_candidates = [candidate_by_key[(sig["symbol"], sig["direction"])] for sig in kept]
    for sig, why in dropped:
        logging.info("AUDIT FILTER DROPPED %s %s: %s", sig.get("symbol"), sig.get("direction"), why)
    candidates.sort(key=lambda item: item["score"], reverse=True)

    print("\nMERCURYEDGE MARKET INTELLIGENCE SCAN")
    print(f"Signal window: {slot}")
    print(f"Markets loaded: {len(market_data)}/{len(MARKETS)}")
    print(f"Historical profiles loaded: {historical_loaded}")
    print(f"Setups found: {len(candidates)}")
    print(f"Regime/exposure selected: {len(selected_candidates)}/{MAX_SETUPS}")
    print(f"Existing open exposure: {len(open_signals)}")
    print(f"Guardrails: ADX>={MIN_ADX:g}, 4H={'ON' if REQUIRE_HTF_TREND else 'OFF'}, currency cap={MAX_CURRENCY_EXPOSURE:g}")
    print(f"Adaptive learning: {selected_candidates[0].get('_setup', {}).get('adaptive_enabled', False) if selected_candidates else False}")
    print(f"News: {news.label}")
    print("=" * 70)

    for item in skipped:
        logging.info(
            "SKIPPED %s %s: %s",
            item.get("symbol"),
            item.get("direction"),
            item.get("reason"),
        )

    if not selected_candidates:
        print("No qualifying setups after regime/exposure filtering.")
        send_telegram(
            "🧠 MERCURYEDGE\n"
            f"{slot.upper()} SIGNAL • NO QUALIFYING SETUPS\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "No setup passed the regime and exposure guardrails in this scan window.\n"
            "No trade signal was issued.\n"
            "Paper/research signals only."
        )
        return

    selected = []
    for item in selected_candidates:
        market = item["_market"]
        setup = item["_setup"]
        frame = item["_frame"]

        features = build_features(
            market.name,
            setup["direction"],
            setup["entry"],
            setup["sl"],
            setup["tp1"],
            setup["tp2"],
            setup["score"],
            frame,
            ts=setup.get("timestamp"),
            min_adx=MIN_ADX,
        )
        setup.update(
            {
                "regime_adx": features["adx"],
                "regime_htf_trend": features["htf_trend"],
                "regime_htf_agree": features["htf_agree"],
                "atr_pct": features["atr_pct"],
                "risk_pct": features["risk_pct"],
                "rr_tp1": features["rr_tp1"],
                "rr_tp2": features["rr_tp2"],
                "hour_utc": features["hour_utc"],
                "weekday": features["weekday"],
                "ccy_exposure": features["ccy_exposure"],
                "selection_filter": "adx+4h_trend+currency_exposure",
            }
        )
        selected.append((market, setup))

    bulletin = format_bulletin(
        [(market.name, market.category, setup) for market, setup in selected],
        slot,
    )
    print(bulletin)
    delivered = send_telegram(bulletin)
    if delivered:
        # Journal only published signals; failed Telegram delivery must not
        # poison the 12-hour duplicate guard or appear as an issued setup.
        for market, setup in selected:
            record_signal(market, setup, news)
    else:
        logging.error("MercuryEdge generated a bulletin but Telegram delivery failed.")


if __name__ == "__main__":
    main()
