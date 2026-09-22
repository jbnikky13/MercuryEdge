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
        "historical_score": setup.get("historical_score", 0),
        "historical_confidence": setup.get("historical_confidence", 0.0),
        "historical_samples": setup.get("historical_samples", 0),
        "historical_day": setup.get("historical_day"),
        "historical_month": setup.get("historical_month"),
        "historical_volatility": setup.get("historical_volatility"),
        "historical_regime": setup.get("historical_regime"),
        "historical_win_rate_3d": setup.get("historical_win_rate_3d"),
        "historical_note": setup.get("historical_note"),
        "crossmarket_score": setup.get("crossmarket_score", 0),
        "crossmarket_confidence": setup.get("crossmarket_confidence", 0.0),
        "crossmarket_agreement": setup.get("crossmarket_agreement", 0.0),
        "crossmarket_observations": setup.get("crossmarket_observations", 0),
        "crossmarket_relationships": list(setup.get("crossmarket_relationships", ())),
        "crossmarket_note": setup.get("crossmarket_note"),
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
