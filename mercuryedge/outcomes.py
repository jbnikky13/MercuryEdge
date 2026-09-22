from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

JOURNAL_PATH = Path("data/journal.jsonl")
OUTCOME_PATH = Path("data/outcomes.jsonl")


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _save(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def evaluate_signal(signal: dict, candles: pd.DataFrame, horizon: int = 24) -> dict:
    ts = pd.Timestamp(signal["signal_time"])
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")

    future = candles[pd.to_datetime(candles.index, utc=True) > ts].head(horizon)
    if future.empty:
        return {"status": "UNRESOLVED", "reason": "No future candles"}

    direction = signal["direction"]
    tp1_reached = False
    tp1_time = None

    for index, candle in future.iterrows():
        if direction == "BUY":
            hit_sl = candle["Low"] <= signal["sl"]
            hit_tp2 = candle["High"] >= signal["tp2"]
            hit_tp1 = candle["High"] >= signal["tp1"]
        else:
            hit_sl = candle["High"] >= signal["sl"]
            hit_tp2 = candle["Low"] <= signal["tp2"]
            hit_tp1 = candle["Low"] <= signal["tp1"]

        # Conservative same-candle ordering: if SL and a target are both
        # touched before we know intrabar order, treat the signal as stopped.
        if hit_sl:
            return {
                "status": "SL",
                "resolved_at": str(index),
                "tp1_reached": tp1_reached,
                "tp1_at": tp1_time,
            }

        if hit_tp2:
            return {
                "status": "TP2",
                "resolved_at": str(index),
                "tp1_reached": tp1_reached or hit_tp1,
                "tp1_at": tp1_time or (str(index) if hit_tp1 else None),
            }

        if hit_tp1 and not tp1_reached:
            tp1_reached = True
            tp1_time = str(index)

    if tp1_reached:
        return {
            "status": "TP1",
            "resolved_at": tp1_time,
            "tp1_reached": True,
            "tp1_at": tp1_time,
        }

    return {"status": "UNRESOLVED", "resolved_at": str(future.index[-1])}


def attribute(rows: list[dict]) -> dict:
    groups = defaultdict(list)
    for row in rows:
        if row.get("status") not in {"TP1", "TP2", "SL"}:
            continue

        factors = {
            "historical_positive": row.get("historical_score", 0) > 0,
            "historical_negative": row.get("historical_score", 0) < 0,
            "crossmarket_positive": row.get("crossmarket_score", 0) > 0,
            "crossmarket_negative": row.get("crossmarket_score", 0) < 0,
            "high_crossmarket_agreement": row.get("crossmarket_agreement", 0) >= 0.67,
        }
        for factor, enabled in factors.items():
            if enabled:
                groups[factor].append(row["status"] in {"TP1", "TP2"})

    report = {}
    for factor, outcomes in groups.items():
        report[factor] = {
            "samples": len(outcomes),
            "wins": sum(outcomes),
            "win_rate": round(sum(outcomes) / len(outcomes), 4) if outcomes else 0,
        }
    return report


def resolve_journal(candle_loader, horizon: int = 24) -> dict:
    signals = _load(JOURNAL_PATH)
    existing = _load(OUTCOME_PATH)
    resolved_ids = {
        (row.get("market"), row.get("signal_time"))
        for row in existing
    }

    new_rows = []
    for signal in signals:
        key = (signal.get("market"), signal.get("signal_time"))
        if key in resolved_ids:
            continue
        candles = candle_loader(signal["symbol"], signal["signal_time"])
        result = evaluate_signal(signal, candles, horizon=horizon)
        if result["status"] == "UNRESOLVED":
            continue
        new_rows.append({**signal, **result})

    if new_rows:
        _save(OUTCOME_PATH, existing + new_rows)

    all_rows = existing + new_rows
    return {
        "new_resolutions": len(new_rows),
        "total_resolved": len(all_rows),
        "factor_report": attribute(all_rows),
    }
