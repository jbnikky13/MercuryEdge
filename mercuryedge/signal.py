from __future__ import annotations

import logging

import requests

from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


def _fmt(value: float) -> str:
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 100:
        return f"{value:.2f}"
    if value >= 10:
        return f"{value:.3f}"
    return f"{value:.5f}"


def format_signal(name: str, category: str, setup: dict) -> str:
    history = setup.get("historical_win_rate_3d")
    history_rate = f"{history * 100:.1f}%" if history is not None else "N/A"
    relations = ", ".join(setup.get("crossmarket_relationships", ())) or "N/A"
    icon = {"forex": "💱", "commodity": "🛢️", "index": "📈"}.get(category, "📊")
    adaptive = (
        setup.get("adaptive_historical_modifier", 0)
        + setup.get("adaptive_crossmarket_modifier", 0)
        + setup.get("adaptive_agreement_modifier", 0)
    )
    return "\n".join(
        [
            f"{icon} {category.upper()} SETUP",
            "",
            f"{setup['direction']} {name} @ {_fmt(setup['entry'])}",
            "",
            f"TP1. {_fmt(setup['tp1'])}",
            f"TP2. {_fmt(setup['tp2'])}",
            f"SL. {_fmt(setup['sl'])}",
            "",
            f"R:R 1:{setup['rr1']:.1f} / 1:{setup['rr2']:.1f}",
            f"TREND. {setup['trend']}",
            f"SETUP. {setup['setup']}",
            f"SCORE. {setup['score']}/100",
            "",
            "HISTORICAL INTELLIGENCE",
            f"3D HIT RATE: {history_rate}",
            f"Analogues. {setup.get('historical_samples', 0)}",
            f"Regime. {setup.get('historical_regime') or 'N/A'} / {setup.get('historical_volatility') or 'N/A'}",
            f"Pattern. {setup.get('historical_day') or 'N/A'} + month {setup.get('historical_month') or 'N/A'}",
            f"History modifier. {setup.get('historical_score', 0):+d}",
            "",
            "CROSS-MARKET INTELLIGENCE",
            f"CONFIRMATION: {setup.get('crossmarket_score', 0):+d}",
            f"AGREEMENT: {setup.get('crossmarket_agreement', 0) * 100:.0f}%",
            f"EVIDENCE: {relations}",
            f"ADAPTIVE MODIFIER: {adaptive:+d}",
            "",
            "Historical/cross-market behavior is evidence, not a guarantee.",
            "MANAGE RISK ⚠️",
        ]
    )


def format_bulletin(setups: list[tuple[str, str, dict]], slot: str) -> str:
    lines = [
        "🧠 MERCURYEDGE",
        f"{slot.upper()} SIGNAL • {len(setups)} SETUPS",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    for index, (name, category, setup) in enumerate(setups, 1):
        lines.extend([f"SETUP #{index}", format_signal(name, category, setup), "━━━━━━━━━━━━━━━━━━━━"])
    lines.append("Paper/research signals only • MANAGE RISK ⚠️")
    return "\n".join(lines)


def send_telegram(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Telegram delivery not configured: TELEGRAM_BOT_TOKEN is missing.")
        return False
    if not TELEGRAM_CHAT_ID:
        logger.error("Telegram delivery not configured: TELEGRAM_CHAT_ID is missing.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            logger.error("Telegram API rejected message: %s", payload)
            return False
        logger.info(
            "Telegram delivery successful: message_id=%s",
            payload.get("result", {}).get("message_id"),
        )
        return True
    except requests.RequestException as exc:
        logger.error("Telegram HTTP delivery failed: %s", exc)
        return False
    except ValueError as exc:
        logger.error("Telegram returned invalid JSON: %s", exc)
        return False


def send_telegram_test() -> bool:
    return send_telegram(
        "🧪 MERCURYEDGE TELEGRAM TEST\n"
        "Telegram delivery is configured and reachable.\n"
        "Paper/research signals only."
    )
