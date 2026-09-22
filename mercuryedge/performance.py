from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

OUTCOME_PATH = Path("data/outcomes.jsonl")
REPORT_PATH = Path("data/performance.json")


def load_rows() -> list[dict]:
    if not OUTCOME_PATH.exists():
        return []
    return [json.loads(x) for x in OUTCOME_PATH.read_text(encoding="utf-8").splitlines() if x.strip()]


def _win(row: dict) -> bool:
    return row.get("status") in {"TP1", "TP2"}


def _rr_result(row: dict) -> float:
    if row.get("status") == "TP2":
        return float(row.get("rr2", 0))
    if row.get("status") == "TP1":
        return float(row.get("rr1", 0))
    if row.get("status") == "SL":
        return -1.0
    return 0.0


def _group(rows: list[dict], key):
    groups = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    return groups


def _summary(rows: list[dict]) -> dict:
    resolved = [r for r in rows if r.get("status") in {"TP1", "TP2", "SL"}]
    wins = [r for r in resolved if _win(r)]
    rr = [_rr_result(r) for r in resolved]
    return {
        "signals": len(rows),
        "resolved": len(resolved),
        "unresolved": len(rows) - len(resolved),
        "tp1": sum(r.get("status") == "TP1" for r in resolved),
        "tp2": sum(r.get("status") == "TP2" for r in resolved),
        "sl": sum(r.get("status") == "SL" for r in resolved),
        "win_rate": round(len(wins) / len(resolved), 4) if resolved else None,
        "average_r": round(float(np.mean(rr)), 4) if rr else None,
        "median_r": round(float(np.median(rr)), 4) if rr else None,
    }


def build_report(rows: list[dict]) -> dict:
    report = {"version": 1, "overall": _summary(rows), "factors": {}}

    factor_specs = {
        "historical": lambda r: (
            "POSITIVE" if float(r.get("historical_score", 0)) >= 4
            else "NEGATIVE" if float(r.get("historical_score", 0)) <= -4
            else "NEUTRAL"
        ),
        "crossmarket": lambda r: (
            "POSITIVE" if float(r.get("crossmarket_score", 0)) >= 4
            else "NEGATIVE" if float(r.get("crossmarket_score", 0)) <= -4
            else "NEUTRAL"
        ),
        "agreement": lambda r: (
            "HIGH" if float(r.get("crossmarket_agreement", 0)) >= 0.67
            else "LOW"
        ),
        "direction": lambda r: r.get("direction", "UNKNOWN"),
        "category": lambda r: r.get("category", "UNKNOWN"),
    }

    for factor, key in factor_specs.items():
        report["factors"][factor] = {
            str(bucket): _summary(bucket_rows)
            for bucket, bucket_rows in _group(rows, key).items()
        }

    return report


def write_report(rows: list[dict] | None = None) -> dict:
    report = build_report(rows if rows is not None else load_rows())
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(write_report(), indent=2))
