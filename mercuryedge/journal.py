from __future__ import annotations

import json
from pathlib import Path

JOURNAL_PATH = Path("data/journal.jsonl")


def record_signal(market, setup: dict, news=None) -> None:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "market": market.name,
        "symbol": market.symbol,
        "category": market.category,
        "direction": setup["direction"],
        "setup": setup["setup"],
        "trend": setup["trend"],
        "score": setup["score"],
        "entry": setup["entry"],
        "tp1": setup["tp1"],
        "tp2": setup["tp2"],
        "sl": setup["sl"],
        "rr1": setup["rr1"],
        "rr2": setup["rr2"],
        "signal_time": setup["timestamp"],
        "news_risk": news.label if news else None,
        "news_reason": news.reason if news else None,
        "status": "OPEN",
    }
    with JOURNAL_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def read_journal() -> list[dict]:
    if not JOURNAL_PATH.exists():
        return []
    rows = []
    for line in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows
