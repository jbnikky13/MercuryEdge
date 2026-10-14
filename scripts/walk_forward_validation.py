"""Chronological walk-forward validation for the current historical signal replay.

This is a research-only selector experiment. Each test window is evaluated using
symbol/direction groups that qualified on earlier training data only. Training
rows whose 24-hour outcome horizon overlaps the test boundary are purged.
No live signal rules are changed by this script.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(os.getenv("RESEARCH_OUTPUT", "research_data"))
POLICY = "tp1_full_R"
DEFAULT_COSTS_R = (0.0, 0.05, 0.10)
TRAIN_DAYS = int(os.getenv("WALK_FORWARD_TRAIN_DAYS", "365"))
TEST_DAYS = int(os.getenv("WALK_FORWARD_TEST_DAYS", "90"))
STEP_DAYS = int(os.getenv("WALK_FORWARD_STEP_DAYS", "90"))
HORIZON_HOURS = int(os.getenv("WALK_FORWARD_HORIZON_HOURS", "24"))
MIN_TRAIN_TRADES = int(os.getenv("WALK_FORWARD_MIN_TRAIN_TRADES", "30"))
SELECTION_COST_R = float(os.getenv("WALK_FORWARD_SELECTION_COST_R", "0.05"))
MIN_TRAIN_EDGE_R = float(os.getenv("WALK_FORWARD_MIN_TRAIN_EDGE_R", "0.02"))
COSTS_R = tuple(float(x.strip()) for x in os.getenv(
    "WALK_FORWARD_COSTS_R", ",".join(map(str, DEFAULT_COSTS_R))
).split(",") if x.strip())


def _metrics(values: pd.Series) -> dict:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return {
            "trades": 0, "mean_R": None, "median_R": None,
            "win_rate_pct": None, "profit_factor": None, "max_drawdown_R": None,
        }
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    equity = values.cumsum()
    drawdown = equity - equity.cummax().clip(lower=0)
    return {
        "trades": int(len(values)),
        "mean_R": round(float(values.mean()), 5),
        "median_R": round(float(values.median()), 5),
        "win_rate_pct": round(float((values > 0).mean() * 100), 2),
        "profit_factor": round(gains / losses, 4) if losses > 0 else (None if gains == 0 else float("inf")),
        "max_drawdown_R": round(float(drawdown.min()), 4),
    }


def _prepare_trades(trades: pd.DataFrame) -> pd.DataFrame:
    required = {"ts", "symbol", "direction", POLICY}
    missing = required - set(trades.columns)
    if missing:
        raise ValueError(f"Missing required replay columns: {sorted(missing)}")
    data = trades.copy()
    data["ts"] = pd.to_datetime(data["ts"], utc=True, errors="coerce")
    data[POLICY] = pd.to_numeric(data[POLICY], errors="coerce")
    data = data.dropna(subset=["ts", "symbol", "direction", POLICY])
    return data.sort_values(["ts", "symbol"]).reset_index(drop=True)


def _eligible_groups(
    train: pd.DataFrame,
    min_train_trades: int = MIN_TRAIN_TRADES,
    selection_cost_r: float = SELECTION_COST_R,
    min_train_edge_r: float = MIN_TRAIN_EDGE_R,
) -> dict[tuple[str, str], dict]:
    """Select groups from training outcomes only, after the assumed selection cost."""
    eligible = {}
    if train.empty:
        return eligible
    for (symbol, direction), group in train.groupby(["symbol", "direction"]):
        if len(group) < min_train_trades:
            continue
        mean_net = float(group[POLICY].mean()) - selection_cost_r
        if mean_net >= min_train_edge_r:
            eligible[(str(symbol), str(direction))] = {
                "train_trades": int(len(group)),
                "train_mean_gross_R": round(float(group[POLICY].mean()), 5),
                "train_mean_net_R": round(mean_net, 5),
            }
    return eligible


def walk_forward(
    trades: pd.DataFrame,
    train_days: int = TRAIN_DAYS,
    test_days: int = TEST_DAYS,
    step_days: int = STEP_DAYS,
    horizon_hours: int = HORIZON_HOURS,
    min_train_trades: int = MIN_TRAIN_TRADES,
    selection_cost_r: float = SELECTION_COST_R,
    min_train_edge_r: float = MIN_TRAIN_EDGE_R,
    costs_r: tuple[float, ...] = COSTS_R,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return fold-level results, combined out-of-sample results and metadata."""
    if train_days <= 0 or test_days <= 0 or step_days <= 0 or horizon_hours < 0:
        raise ValueError("Window lengths must be positive and horizon cannot be negative")
    data = _prepare_trades(trades)
    if data.empty:
        return pd.DataFrame(), pd.DataFrame(), {
            "status": "insufficient_data", "input_trades": 0, "folds": 0,
            "reason": "No valid replay trades were available.",
        }

    earliest, latest = data["ts"].min(), data["ts"].max()
    train_delta = pd.Timedelta(days=train_days)
    test_delta = pd.Timedelta(days=test_days)
    step_delta = pd.Timedelta(days=step_days)
    purge_delta = pd.Timedelta(hours=horizon_hours)
    test_start = earliest + train_delta
    fold_rows: list[dict] = []
    oos_records: list[dict] = []
    fold_number = 0

    while test_start <= latest:
        train_start = test_start - train_delta
        # A trade's forward outcome must have matured before the test starts.
        train_end = test_start - purge_delta
        test_end = test_start + test_delta
        train = data[(data["ts"] >= train_start) & (data["ts"] < train_end)]
        test = data[(data["ts"] >= test_start) & (data["ts"] < test_end)]
        if test.empty:
            test_start += step_delta
            continue

        fold_number += 1
        eligible = _eligible_groups(
            train, min_train_trades=min_train_trades,
            selection_cost_r=selection_cost_r, min_train_edge_r=min_train_edge_r,
        )
        keys = set(eligible)
        test = test.copy()
        test["selector_eligible"] = [
            (str(row.symbol), str(row.direction)) in keys
            for row in test[["symbol", "direction"]].itertuples(index=False)
        ]
        eligible_label = ";".join(f"{s}:{d}" for s, d in sorted(keys))

        for mode, sample in (
            ("baseline_all_signals", test),
            ("walk_forward_filtered", test[test["selector_eligible"]]),
        ):
            for cost in costs_r:
                net = pd.to_numeric(sample[POLICY], errors="coerce") - cost
                metrics = _metrics(net)
                fold_rows.append({
                    "fold": fold_number,
                    "train_start_utc": train_start.isoformat(),
                    "train_end_exclusive_utc": train_end.isoformat(),
                    "test_start_utc": test_start.isoformat(),
                    "test_end_exclusive_utc": min(test_end, latest + pd.Timedelta(nanoseconds=1)).isoformat(),
                    "train_trades": int(len(train)),
                    "eligible_symbol_direction_groups": len(keys),
                    "eligible_groups": eligible_label,
                    "mode": mode,
                    "assumed_round_trip_cost_R": cost,
                    **metrics,
                })
                for idx, row in sample.iterrows():
                    oos_records.append({
                        "fold": fold_number, "ts": row["ts"], "symbol": row["symbol"],
                        "direction": row["direction"], "mode": mode,
                        "assumed_round_trip_cost_R": cost,
                        "net_R": float(row[POLICY]) - cost,
                    })
        test_start += step_delta

    fold_df = pd.DataFrame(fold_rows)
    if oos_records:
        record_df = pd.DataFrame(oos_records)
        summary_rows = []
        for (mode, cost), group in record_df.groupby(["mode", "assumed_round_trip_cost_R"], sort=True):
            ordered = group.sort_values(["ts", "symbol", "fold"])
            summary_rows.append({
                "mode": mode, "assumed_round_trip_cost_R": float(cost),
                **_metrics(ordered["net_R"]),
                "positive_test_folds_pct": round(
                    float((group.groupby("fold")["net_R"].mean() > 0).mean() * 100), 2
                ),
                "test_folds": int(group["fold"].nunique()),
            })
        summary_df = pd.DataFrame(summary_rows)
    else:
        summary_df = pd.DataFrame()

    report = {
        "status": "completed" if fold_number else "insufficient_data",
        "input_trades": int(len(data)),
        "first_signal_utc": earliest.isoformat(),
        "last_signal_utc": latest.isoformat(),
        "folds": int(fold_number),
        "train_days": train_days,
        "test_days": test_days,
        "step_days": step_days,
        "outcome_horizon_hours": horizon_hours,
        "training_boundary_purge_hours": horizon_hours,
        "selection_policy": POLICY,
        "selection_rule": (
            f"Keep symbol/direction groups with at least {min_train_trades} matured training trades "
            f"and training mean net R >= {min_train_edge_r:.3f} after selection cost "
            f"{selection_cost_r:.3f}R; apply only to the following unseen test window."
        ),
        "evaluation_cost_scenarios_R": list(costs_r),
        "test_windows_are_chronological_and_non_overlapping": True,
        "training_outcomes_are_purged_before_test_boundary": True,
        "strategy_rules_changed": False,
        "live_signal_filter_enabled": False,
        "warning": (
            "Research-only selector experiment. Yahoo Finance prices are not verified broker fills; "
            "cost scenarios are assumptions. Positive walk-forward results would still require "
            "broker-specific costs, robustness checks, and paper trading before any live use."
        ),
    }
    return fold_df, summary_df, report


def main() -> int:
    source = ROOT / "replayed-signals.csv"
    if not source.exists():
        raise FileNotFoundError(f"Missing {source}; run scripts/research_historical.py first")
    trades = pd.read_csv(source)
    folds, summary, report = walk_forward(trades)
    ROOT.mkdir(parents=True, exist_ok=True)
    folds.to_csv(ROOT / "walk-forward-folds.csv", index=False)
    summary.to_csv(ROOT / "walk-forward-summary.csv", index=False)
    (ROOT / "walk-forward-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("\nWalk-forward out-of-sample summary:")
    print(summary.to_string(index=False) if not summary.empty else "No eligible test windows.")
    if report["status"] != "completed":
        print("WARNING: insufficient data for the configured walk-forward windows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
