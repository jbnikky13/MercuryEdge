from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

OUTCOME_PATH = Path("data/outcomes.jsonl")
CALIBRATION_PATH = Path("data/calibration.json")


def load_outcomes() -> list[dict]:
    if not OUTCOME_PATH.exists():
        return []
    return [
        json.loads(line)
        for line in OUTCOME_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _win(row: dict) -> bool:
    return row.get("status") in {"TP1", "TP2"}


def _bucket(value: float) -> str:
    if value <= -4:
        return "NEGATIVE"
    if value >= 4:
        return "POSITIVE"
    return "NEUTRAL"


def calibrate(rows: list[dict], min_samples: int = 30) -> dict:
    """Estimate bounded factor weights from completed out-of-sample outcomes.

    Factors are evaluated only against outcomes that occurred after the signal.
    Weights are deliberately small and capped to avoid turning correlation into
    an overfit trading rule.
    """
    if not rows:
        return {"version": 1, "samples": 0, "factors": {}}

    specs = {
        "historical": lambda r: _bucket(float(r.get("historical_score", 0))),
        "crossmarket": lambda r: _bucket(float(r.get("crossmarket_score", 0))),
        "agreement": lambda r: (
            "HIGH" if float(r.get("crossmarket_agreement", 0)) >= 0.67
            else "LOW"
        ),
    }

    result = {"version": 1, "samples": len(rows), "factors": {}}

    for factor, key_fn in specs.items():
        groups = defaultdict(list)
        for row in rows:
            groups[key_fn(row)].append(row)

        factor_report = {}
        for bucket, bucket_rows in groups.items():
            if len(bucket_rows) < min_samples:
                continue

            wins = np.mean([_win(row) for row in bucket_rows])
            baseline = np.mean([_win(row) for row in rows])
            edge = float(wins - baseline)

            # 100% edge would still only move the live score by 6 points.
            modifier = int(np.clip(round(edge * 12), -6, 6))
            factor_report[bucket] = {
                "samples": len(bucket_rows),
                "win_rate": round(float(wins), 4),
                "baseline_win_rate": round(float(baseline), 4),
                "edge": round(edge, 4),
                "modifier": modifier,
            }

        result["factors"][factor] = factor_report

    CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALIBRATION_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return result


def main() -> None:
    rows = load_outcomes()
    report = calibrate(rows)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
