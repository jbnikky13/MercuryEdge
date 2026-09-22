from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

JOURNAL_PATH = Path("data/journal.jsonl")


def _batch_id(timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        hour = dt.astimezone(timezone.utc).hour
    except ValueError:
        hour = 0
    slot = "morning" if hour < 11 else "afternoon" if hour < 16 else "evening"
    return f"{timestamp[:10]}-{slot}"


def record_signal(market, setup: dict, news=None) -> None:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    signal_time = setup["timestamp"]
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
        "signal_time": signal_time,
        "signal_batch": _batch_id(signal_time),
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
        "adaptive_enabled": setup.get("adaptive_enabled", False),
        "adaptive_historical_modifier": setup.get("adaptive_historical_modifier", 0),
        "adaptive_crossmarket_modifier": setup.get("adaptive_crossmarket_modifier", 0),
        "adaptive_agreement_modifier": setup.get("adaptive_agreement_modifier", 0),
        "status": "OPEN",
    }
    with JOURNAL_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def read_journal() -> list[dict]:
    if not JOURNAL_PATH.exists():
        return []
    return [json.loads(line) for line in JOURNAL_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
