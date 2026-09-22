from __future__ import annotations

import json
from pathlib import Path

import numpy as np

OUTCOME_PATH = Path("data/outcomes.jsonl")
CALIBRATION_PATH = Path("data/calibration.json")
WALKFORWARD_PATH = Path("data/walkforward.json")


def load_outcomes() -> list[dict]:
    if not OUTCOME_PATH.exists():
        return []
    rows = [json.loads(x) for x in OUTCOME_PATH.read_text(encoding="utf-8").splitlines() if x.strip()]
    return sorted(rows, key=lambda r: r.get("signal_time", ""))


def _win(row: dict) -> bool:
    return row.get("status") in {"TP1", "TP2"}


def _bucket(value: float) -> str:
    if value <= -4:
        return "NEGATIVE"
    if value >= 4:
        return "POSITIVE"
    return "NEUTRAL"


def _factor_bucket(row: dict, factor: str) -> str:
    if factor == "historical":
        return _bucket(float(row.get("historical_score", 0)))
    if factor == "crossmarket":
        return _bucket(float(row.get("crossmarket_score", 0)))
    if factor == "agreement":
        return "HIGH" if float(row.get("crossmarket_agreement", 0)) >= 0.67 else "LOW"
    raise ValueError(f"unknown factor: {factor}")


def calibrate(rows: list[dict], min_samples: int = 30) -> dict:
    if not rows:
        result = {"version": 2, "samples": 0, "factors": {}}
        CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
        CALIBRATION_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    baseline = float(np.mean([_win(row) for row in rows]))
    result = {"version": 2, "samples": len(rows), "baseline_win_rate": round(baseline, 4), "factors": {}}

    for factor in ("historical", "crossmarket", "agreement"):
        factor_report = {}
        for bucket in sorted({_factor_bucket(row, factor) for row in rows}):
            bucket_rows = [r for r in rows if _factor_bucket(r, factor) == bucket]
            if len(bucket_rows) < min_samples:
                continue
            win_rate = float(np.mean([_win(r) for r in bucket_rows]))
            edge = win_rate - baseline
            factor_report[bucket] = {
                "samples": len(bucket_rows),
                "win_rate": round(win_rate, 4),
                "baseline_win_rate": round(baseline, 4),
                "edge": round(edge, 4),
                "modifier": int(np.clip(round(edge * 12), -6, 6)),
            }
        result["factors"][factor] = factor_report

    CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALIBRATION_PATH.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def walk_forward(rows: list[dict], train_size: int = 60, test_size: int = 20, min_bucket: int = 10) -> dict:
    """Rolling train-then-unseen-test validation with no future leakage."""
    rows = sorted(rows, key=lambda r: r.get("signal_time", ""))
    folds = []

    start = 0
    while start + train_size + test_size <= len(rows):
        train = rows[start:start + train_size]
        test = rows[start + train_size:start + train_size + test_size]
        baseline = float(np.mean([_win(r) for r in train])) if train else 0.0

        learned = {}
        for factor in ("historical", "crossmarket", "agreement"):
            learned[factor] = {}
            for bucket in ("NEGATIVE", "NEUTRAL", "POSITIVE", "HIGH", "LOW"):
                bucket_rows = [r for r in train if _factor_bucket(r, factor) == bucket]
                if len(bucket_rows) >= min_bucket:
                    wr = float(np.mean([_win(r) for r in bucket_rows]))
                    learned[factor][bucket] = int(np.clip(round((wr - baseline) * 12), -6, 6))

        selected = []
        raw_wins = []
        modifiers = []
        for row in test:
            raw_wins.append(_win(row))
            modifier = sum(
                learned.get(factor, {}).get(_factor_bucket(row, factor), 0)
                for factor in ("historical", "crossmarket", "agreement")
            )
            modifiers.append(modifier)
            if float(row.get("score", 0)) + modifier >= 60:
                selected.append(_win(row))

        folds.append({
            "train_start": train[0].get("signal_time"),
            "train_end": train[-1].get("signal_time"),
            "test_start": test[0].get("signal_time"),
            "test_end": test[-1].get("signal_time"),
            "train_samples": len(train),
            "test_samples": len(test),
            "train_baseline_win_rate": round(baseline, 4),
            "test_baseline_win_rate": round(float(np.mean(raw_wins)), 4),
            "selected_test_samples": len(selected),
            "selected_test_win_rate": round(float(np.mean(selected)), 4) if selected else None,
            "average_modifier": round(float(np.mean(modifiers)), 3) if modifiers else 0.0,
        })
        start += test_size

    selected_rates = [f["selected_test_win_rate"] for f in folds if f["selected_test_win_rate"] is not None]
    report = {
        "version": 1,
        "method": "rolling_train_then_unseen_test",
        "train_size": train_size,
        "test_size": test_size,
        "fold_count": len(folds),
        "folds": folds,
        "mean_selected_test_win_rate": round(float(np.mean(selected_rates)), 4) if selected_rates else None,
    }
    WALKFORWARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    WALKFORWARD_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> None:
    rows = load_outcomes()
    print(json.dumps({"calibration": calibrate(rows), "walk_forward": walk_forward(rows)}, indent=2))


if __name__ == "__main__":
    main()
