"""Duration-aware, point-in-time walk-forward validation for the live-pipeline replay.

Uses only fully matured five-day TP1 outcomes. The selector is evaluated out of
sample by symbol, direction, and intended holding period; training outcomes are
purged by the maximum five-day horizon. Research-only; does not alter live rules.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(os.getenv("RESEARCH_OUTPUT", "research_data"))
RETURN_COLUMN = "tp1_full_R_5d"
GROUP_COLUMNS = ["symbol", "direction", "holding_period"]
TRAIN_DAYS = int(os.getenv("DURATION_WF_TRAIN_DAYS", "365"))
TEST_DAYS = int(os.getenv("DURATION_WF_TEST_DAYS", "90"))
STEP_DAYS = int(os.getenv("DURATION_WF_STEP_DAYS", "90"))
HORIZON_HOURS = int(os.getenv("DURATION_WF_HORIZON_HOURS", "120"))
MIN_TRAIN_TRADES = int(os.getenv("DURATION_WF_MIN_TRAIN_TRADES", "8"))
SELECTION_COST_R = float(os.getenv("DURATION_WF_SELECTION_COST_R", "0.05"))
MIN_TRAIN_EDGE_R = float(os.getenv("DURATION_WF_MIN_TRAIN_EDGE_R", "0.02"))
COSTS_R = tuple(float(x) for x in os.getenv("DURATION_WF_COSTS_R", "0,0.05,0.10").split(",") if x.strip())


def metrics(values: pd.Series) -> dict:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return {"trades": 0, "mean_R": None, "median_R": None, "win_rate_pct": None,
                "profit_factor": None, "max_drawdown_R": None}
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    equity = values.cumsum()
    drawdown = equity - equity.cummax().clip(lower=0)
    return {"trades": int(len(values)), "mean_R": round(float(values.mean()), 5),
            "median_R": round(float(values.median()), 5),
            "win_rate_pct": round(float((values > 0).mean() * 100), 2),
            "profit_factor": round(gains / losses, 4) if losses else (None if gains == 0 else float("inf")),
            "max_drawdown_R": round(float(drawdown.min()), 4)}


def prepare(trades: pd.DataFrame, horizon_hours: int = HORIZON_HOURS) -> pd.DataFrame:
    required = {"scan_ts", "symbol", "direction", "holding_period", RETURN_COLUMN}
    missing = required - set(trades.columns)
    if missing:
        raise ValueError(f"Missing duration-aware replay columns: {sorted(missing)}")
    data = trades.copy()
    data["scan_ts"] = pd.to_datetime(data["scan_ts"], utc=True, errors="coerce")
    data[RETURN_COLUMN] = pd.to_numeric(data[RETURN_COLUMN], errors="coerce")
    data = data.dropna(subset=["scan_ts", "symbol", "direction", "holding_period", RETURN_COLUMN])
    # Keep one signal per symbol per maximum outcome horizon to reduce overlap.
    kept = []
    last_seen = {}
    for _, row in data.sort_values(["scan_ts", "symbol"]).iterrows():
        ts = row["scan_ts"]
        if row["symbol"] in last_seen and ts - last_seen[row["symbol"]] < pd.Timedelta(hours=horizon_hours):
            continue
        kept.append(row)
        last_seen[row["symbol"]] = ts
    if not kept:
        return data.iloc[0:0].copy()
    return pd.DataFrame(kept).sort_values(["scan_ts", "symbol"]).reset_index(drop=True)


def validate(trades: pd.DataFrame, train_days: int = TRAIN_DAYS, test_days: int = TEST_DAYS,
             step_days: int = STEP_DAYS, horizon_hours: int = HORIZON_HOURS,
             min_train_trades: int = MIN_TRAIN_TRADES, selection_cost_r: float = SELECTION_COST_R,
             min_train_edge_r: float = MIN_TRAIN_EDGE_R, costs_r: tuple[float, ...] = COSTS_R):
    if min(train_days, test_days, step_days, horizon_hours, min_train_trades) <= 0:
        raise ValueError("Window lengths, horizon and minimum training count must be positive")
    raw_count = len(trades)
    data = prepare(trades, horizon_hours)
    if data.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "insufficient_data", "input_rows": raw_count,
            "matured_rows": 0, "non_overlapping_rows": 0, "folds": 0,
            "reason": f"No fully matured {horizon_hours}-hour outcomes with {RETURN_COLUMN} were available."}

    earliest, latest = data["scan_ts"].min(), data["scan_ts"].max()
    train_delta, test_delta = pd.Timedelta(days=train_days), pd.Timedelta(days=test_days)
    step_delta, purge_delta = pd.Timedelta(days=step_days), pd.Timedelta(hours=horizon_hours)
    test_start = earliest + train_delta
    folds, oos = [], []
    fold_num = 0
    while test_start <= latest:
        train_start = test_start - train_delta
        train_end = test_start - purge_delta
        test_end = test_start + test_delta
        train = data[(data["scan_ts"] >= train_start) & (data["scan_ts"] < train_end)]
        test = data[(data["scan_ts"] >= test_start) & (data["scan_ts"] < test_end)]
        if test.empty:
            test_start += step_delta
            continue
        fold_num += 1
        eligible = set()
        train_stats = {}
        for key, group in train.groupby(GROUP_COLUMNS, dropna=False):
            if len(group) < min_train_trades:
                continue
            gross_mean = float(group[RETURN_COLUMN].mean())
            net_mean = gross_mean - selection_cost_r
            if net_mean >= min_train_edge_r:
                key = tuple(str(v) for v in (key if isinstance(key, tuple) else (key,)))
                eligible.add(key)
                train_stats[key] = {"train_count": len(group), "train_mean_gross_R": round(gross_mean, 5),
                                    "train_mean_net_R": round(net_mean, 5)}
        test = test.copy()
        test["_eligible"] = [tuple(str(row[c]) for c in GROUP_COLUMNS) in eligible
                             for _, row in test.iterrows()]
        for mode, sample in (("baseline_all", test), ("duration_selector", test[test["_eligible"]])):
            for cost in costs_r:
                net = sample[RETURN_COLUMN] - cost
                folds.append({"fold": fold_num, "train_start_utc": train_start.isoformat(),
                    "train_end_exclusive_utc": train_end.isoformat(), "test_start_utc": test_start.isoformat(),
                    "test_end_exclusive_utc": min(test_end, latest + pd.Timedelta(nanoseconds=1)).isoformat(),
                    "train_trades": len(train), "eligible_groups": len(eligible),
                    "mode": mode, "assumed_round_trip_cost_R": cost, **metrics(net)})
                for _, row in sample.iterrows():
                    oos.append({"fold": fold_num, "scan_ts": row["scan_ts"], "symbol": row["symbol"],
                        "direction": row["direction"], "holding_period": row["holding_period"], "mode": mode,
                        "assumed_round_trip_cost_R": cost, "net_R": float(row[RETURN_COLUMN]) - cost})
        test_start += step_delta

    fold_df = pd.DataFrame(folds)
    if oos:
        records = pd.DataFrame(oos)
        summaries = []
        for (mode, cost), group in records.groupby(["mode", "assumed_round_trip_cost_R"]):
            summaries.append({"mode": mode, "assumed_round_trip_cost_R": float(cost),
                **metrics(group.sort_values(["scan_ts", "symbol", "fold"])["net_R"]),
                "positive_test_folds_pct": round(float((group.groupby("fold")["net_R"].mean() > 0).mean() * 100), 2),
                "test_folds": int(group["fold"].nunique())})
        summary_df = pd.DataFrame(summaries)
    else:
        summary_df = pd.DataFrame()
    report = {"status": "completed" if fold_num else "insufficient_data", "input_rows": raw_count,
        "matured_rows": int(trades[RETURN_COLUMN].notna().sum()) if RETURN_COLUMN in trades else 0,
        "non_overlapping_rows": int(len(data)), "first_signal_utc": earliest.isoformat(),
        "last_signal_utc": latest.isoformat(), "folds": fold_num, "train_days": train_days,
        "test_days": test_days, "step_days": step_days, "outcome_horizon_hours": horizon_hours,
        "training_boundary_purge_hours": horizon_hours, "return_column": RETURN_COLUMN,
        "selection_groups": GROUP_COLUMNS, "minimum_training_trades_per_group": min_train_trades,
        "selection_rule": f"Group must have >= {min_train_trades} matured training outcomes and mean net R >= {min_train_edge_r:.3f} after {selection_cost_r:.3f}R assumed cost.",
        "cost_scenarios_R": list(costs_r), "training_outcomes_purged_before_test": True,
        "test_windows_chronological": True, "live_filter_changed": False,
        "warning": "Research-only. Uses Yahoo Finance proxy prices and assumed costs; no broker fills, spread, slippage, funding or contract mapping. Never enable live trading based on this report alone."}
    return fold_df, summary_df, report


def main() -> int:
    source = ROOT / "live-pipeline-replay.csv"
    if not source.exists():
        raise FileNotFoundError(f"Missing {source}; run scripts/replay_live_pipeline.py first")
    trades = pd.read_csv(source)
    folds, summary, report = validate(trades)
    ROOT.mkdir(parents=True, exist_ok=True)
    folds.to_csv(ROOT / "duration-walk-forward-folds.csv", index=False)
    summary.to_csv(ROOT / "duration-walk-forward-summary.csv", index=False)
    (ROOT / "duration-walk-forward-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("\nDuration-aware out-of-sample summary:")
    print(summary.to_string(index=False) if not summary.empty else "No eligible test windows.")
    return 0 if report["status"] == "completed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
