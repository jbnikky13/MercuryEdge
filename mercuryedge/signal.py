from __future__ import annotations

import requests

from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


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
    icon = {"forex": "💱", "commodity": "🛢️", "index": "📈"}.get(category, "📊")
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
            f"3D directional hit rate. {history_rate}",
            f"Analogues. {setup.get('historical_samples', 0)}",
            f"Regime. {setup.get('historical_regime') or 'N/A'} / {setup.get('historical_volatility') or 'N/A'}",
            f"Pattern. {setup.get('historical_day') or 'N/A'} + month {setup.get('historical_month') or 'N/A'}",
            f"History modifier. {setup.get('historical_score', 0):+d}",
            "",
            "Historical behavior is evidence, not a guarantee.",
            "MANAGE RISK ⚠️",
        ]
    )


def send_telegram(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
        timeout=20,
    )
    response.raise_for_status()
    return True
