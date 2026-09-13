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
    return "\n".join(
        [
            f"{'📊' if category == 'forex' else '🪙'} {category.upper()} SETUP",
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
