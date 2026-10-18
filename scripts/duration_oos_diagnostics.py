"""Out-of-sample market diagnostics, cost stress, and week-cluster bootstrap.

Research only. Replays the existing chronological selector; does not change live rules.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.walk_forward_duration_validation import (
    GROUP_COLUMNS, HORIZON_HOURS, MIN_TRAIN_EDGE_R, MIN_TRAIN_TRADES,
    ROOT, SELECTION_COST_R, STEP_DAYS, TEST_DAYS, TRAIN_DAYS, prepare,
)

COSTS = (0.0, 0.05, 0.10, 0.15, 0.20)
BOOTSTRAP_REPS = 5000
SEED = 20261017


def _pf(values: pd.Series) -> float | None:
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / losses


def collect_oos(trades: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    data = prepare(trades, HORIZON_HOURS)
    if data.empty:
        return pd.DataFrame(), {"status": "insufficient_data", "selected_oos_trades": 0}
    earliest, latest = data.scan_ts.min(), data.scan_ts.max()
    train_delta, test_delta = pd.Timedelta(days=TRAIN_DAYS), pd.Timedelta(days=TEST_DAYS)
    step_delta, purge_delta = pd.Timedelta(days=STEP_DAYS), pd.Timedelta(hours=HORIZON_HOURS)
    start = earliest + train_delta
    rows, fold = [], 0
    while start <= latest:
        train_start = start - train_delta
        train_end = start - purge_delta
        end = start + test_delta
        train = data[(data.scan_ts >= train_start) & (data.scan_ts < train_end)]
        test = data[(data.scan_ts >= start) & (data.scan_ts < end)].copy()
        if test.empty:
            start += step_delta
            continue
        fold += 1
        eligible = set()
        for key, group in train.groupby(GROUP_COLUMNS, dropna=False):
            if len(group) < MIN_TRAIN_TRADES:
                continue
            if float(group.tp1_full_R_5d.mean()) - SELECTION_COST_R >= MIN_TRAIN_EDGE_R:
                eligible.add(tuple(str(v) for v in (key if isinstance(key, tuple) else (key,))))
        test["_eligible"] = [
            tuple(str(row[c]) for c in GROUP_COLUMNS) in eligible
            for _, row in test.iterrows()
        ]
        chosen = test[test["_eligible"]]
        for _, row in chosen.iterrows():
            rows.append({
                "fold": fold, "scan_ts": row.scan_ts, "symbol": str(row.symbol),
                "direction": str(row.direction), "holding_period": str(row.holding_period),
                "gross_R": float(row.tp1_full_R_5d),
                "train_start_utc": train_start.isoformat(),
                "test_start_utc": start.isoformat(),
            })
        start += step_delta
    result = pd.DataFrame(rows)
    report = {
        "status": "completed" if not result.empty else "insufficient_data",
        "selected_oos_trades": int(len(result)),
        "folds_with_selected_trades": int(result.fold.nunique()) if not result.empty else 0,
        "cost_scenarios_R": list(COSTS),
        "train_test_chronology": "rolling chronological windows with 120-hour purge",
        "selection_parameters": {
            "train_days": TRAIN_DAYS, "test_days": TEST_DAYS, "step_days": STEP_DAYS,
            "minimum_train_group_trades": MIN_TRAIN_TRADES,
            "minimum_train_net_edge_R": MIN_TRAIN_EDGE_R,
            "selection_cost_R": SELECTION_COST_R,
        },
        "warning": "Out-of-sample here means relative to each fold's training window, not an untouched holdout after strategy design. Yahoo proxy prices and assumed costs are not broker fills.",
    }
    return result, report


def cost_table(oos: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cost in COSTS:
        v = oos.gross_R - cost if not oos.empty else pd.Series(dtype=float)
        rows.append({
            "assumed_cost_R": cost, "trades": len(v),
            "mean_net_R": float(v.mean()) if len(v) else None,
            "median_net_R": float(v.median()) if len(v) else None,
            "win_rate_pct": float((v > 0).mean() * 100) if len(v) else None,
            "profit_factor": _pf(v) if len(v) else None,
            "positive_folds_pct": float((oos.assign(net=v).groupby("fold").net.mean() > 0).mean() * 100) if len(v) else None,
            "worst_fold_mean_R": float(oos.assign(net=v).groupby("fold").net.mean().min()) if len(v) else None,
        })
    return pd.DataFrame(rows)


def market_table(oos: pd.DataFrame, cost: float = 0.10) -> pd.DataFrame:
    if oos.empty:
        return pd.DataFrame()
    data = oos.copy()
    data["net_R"] = data.gross_R - cost
    rows = []
    for (symbol, direction, duration), group in data.groupby(["symbol", "direction", "holding_period"]):
        rows.append({
            "symbol": symbol, "direction": direction, "holding_period": duration,
            "trades": len(group), "mean_net_R": float(group.net_R.mean()),
            "median_net_R": float(group.net_R.median()),
            "win_rate_pct": float((group.net_R > 0).mean() * 100),
            "profit_factor": _pf(group.net_R),
            "positive_folds_pct": float((group.groupby("fold").net_R.mean() > 0).mean() * 100),
        })
    return pd.DataFrame(rows).sort_values(["trades", "mean_net_R"], ascending=[False, False])


def weekly_block_bootstrap(oos: pd.DataFrame, cost: float = 0.10) -> dict:
    if oos.empty:
        return {"status": "insufficient_data", "confidence_interval_95_R": None}
    data = oos.copy()
    data["net_R"] = data.gross_R - cost
    data["week"] = data.scan_ts.dt.to_period("W").astype(str)
    weekly = data.groupby("week").net_R.mean().to_numpy(dtype=float)
    if len(weekly) < 8:
        return {
            "status": "too_few_week_clusters",
            "week_clusters": int(len(weekly)),
            "mean_trade_net_R": float(data.net_R.mean()),
            "confidence_interval_95_R": None,
            "warning": "Fewer than 8 weekly clusters; do not interpret a bootstrap interval as reliable.",
        }
    rng = np.random.default_rng(SEED)
    draws = np.empty(BOOTSTRAP_REPS)
    for i in range(BOOTSTRAP_REPS):
        sample = rng.choice(weekly, size=len(weekly), replace=True)
        draws[i] = sample.mean()
    return {
        "status": "completed",
        "assumed_cost_R": cost,
        "week_clusters": int(len(weekly)),
        "mean_weekly_cluster_return_R": float(weekly.mean()),
        "mean_trade_net_R": float(data.net_R.mean()),
        "confidence_interval_95_R": [float(np.quantile(draws, .025)), float(np.quantile(draws, .975))],
        "bootstrap_repetitions": BOOTSTRAP_REPS,
        "method": "resample calendar-week cluster means with replacement",
        "warning": "Exploratory cluster bootstrap, not a proof of profitability; overlapping market exposures and regime shifts can remain.",
    }


def main() -> int:
    source = ROOT / "live-pipeline-replay.csv"
    if not source.exists():
        raise FileNotFoundError(f"Missing {source}; run scripts/replay_live_pipeline.py first")
    oos, report = collect_oos(pd.read_csv(source))
    ROOT.mkdir(parents=True, exist_ok=True)
    costs = cost_table(oos)
    markets = market_table(oos)
    bootstrap = weekly_block_bootstrap(oos)
    oos.to_csv(ROOT / "duration-oos-selected-trades.csv", index=False)
    costs.to_csv(ROOT / "duration-oos-cost-stress.csv", index=False)
    markets.to_csv(ROOT / "duration-oos-market-breakdown.csv", index=False)
    (ROOT / "duration-oos-diagnostics-report.json").write_text(
        json.dumps({"walk_forward": report, "weekly_cluster_bootstrap_at_0_10R": bootstrap}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"walk_forward": report, "weekly_cluster_bootstrap_at_0_10R": bootstrap}, indent=2))
    print("\nCost stress:")
    print(costs.to_string(index=False))
    print("\nMarket/direction/duration breakdown at 0.10R cost:")
    print(markets.to_string(index=False) if not markets.empty else "No selected out-of-sample trades.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
