"""Cost-aware walk-forward selection of diagnostic signal filters.

Candidate rules are predefined. Each test fold selects from the prior training
window only, purges 24h outcomes across the boundary, then evaluates the chosen
rule on the next chronological window. This script never changes live rules.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("research_data")
OUTCOME = "tp1_full_R_24h"
COSTS_R = tuple(float(x) for x in os.getenv("SIGNAL_FILTER_COSTS_R", "0,0.05,0.10,0.15,0.20").split(","))
TRAIN_DAYS = int(os.getenv("SIGNAL_FILTER_TRAIN_DAYS", "365"))
TEST_DAYS = int(os.getenv("SIGNAL_FILTER_TEST_DAYS", "90"))
STEP_DAYS = int(os.getenv("SIGNAL_FILTER_STEP_DAYS", "90"))
PURGE_HOURS = int(os.getenv("SIGNAL_FILTER_PURGE_HOURS", "24"))
MIN_TRAIN_TRADES = int(os.getenv("SIGNAL_FILTER_MIN_TRAIN_TRADES", "30"))
SELECTION_COST_R = float(os.getenv("SIGNAL_FILTER_SELECTION_COST_R", "0.10"))
MIN_EDGE_IMPROVEMENT_R = float(os.getenv("SIGNAL_FILTER_MIN_EDGE_IMPROVEMENT_R", "0.03"))

RULES = {
    "BASELINE": lambda d: pd.Series(True, index=d.index),
    "STRETCH_LE_1_ATR": lambda d: d["entry_stretch_atr"] <= 1.0,
    "STRETCH_LE_1_5_ATR": lambda d: d["entry_stretch_atr"] <= 1.5,
    "SCORE_GE_70": lambda d: d["score"] >= 70,
    "CROSSMARKET_GE_5": lambda d: d["crossmarket_score"] >= 5,
    "ANALOGUE_RATE_GE_55": lambda d: d["selected_historical_rate_pct"] >= 55,
    "STRETCH_LE_1_AND_SCORE_GE_70": lambda d: (d["entry_stretch_atr"] <= 1.0) & (d["score"] >= 70),
}


def _profit_factor(values: pd.Series):
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    if losses <= 0:
        return float("inf") if gains > 0 else None
    return gains / losses


def metrics(values: pd.Series) -> dict:
    x = pd.to_numeric(values, errors="coerce").dropna()
    if x.empty:
        return {"trades": 0, "mean_R": None, "median_R": None, "win_rate_pct": None, "profit_factor": None}
    pf = _profit_factor(x)
    return {
        "trades": int(len(x)),
        "mean_R": round(float(x.mean()), 5),
        "median_R": round(float(x.median()), 5),
        "win_rate_pct": round(float((x > 0).mean() * 100), 2),
        "profit_factor": round(pf, 4) if pf is not None and np.isfinite(pf) else pf,
    }


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"scan_ts", "score", "crossmarket_score", "entry_stretch_atr", OUTCOME, "holding_period"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Replay data missing columns: {missing}")
    d = frame.copy()
    d["scan_ts"] = pd.to_datetime(d["scan_ts"], utc=True, errors="coerce")
    numeric = ["score", "crossmarket_score", "entry_stretch_atr", OUTCOME,
               "historical_win_rate_1d_pct", "historical_win_rate_3d_pct", "historical_win_rate_5d_pct"]
    for col in numeric:
        if col not in d:
            d[col] = np.nan
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=["scan_ts", "score", "crossmarket_score", "entry_stretch_atr", OUTCOME]).copy()
    d = d[d["entry_stretch_atr"] >= 0].copy()
    rate_map = {
        "INTRADAY_0_24H": "historical_win_rate_1d_pct",
        "SWING_24_72H": "historical_win_rate_3d_pct",
        "POSITION_3_5D": "historical_win_rate_5d_pct",
    }
    d["selected_historical_rate_pct"] = [
        row.get(rate_map.get(str(row["holding_period"]), ""), np.nan)
        for _, row in d.iterrows()
    ]
    d["net_before_cost_R"] = d[OUTCOME]
    return d.sort_values("scan_ts").reset_index(drop=True)


def select_rule(train: pd.DataFrame) -> tuple[str, dict]:
    baseline = metrics(train[OUTCOME] - SELECTION_COST_R)
    eligible = []
    for name, predicate in RULES.items():
        mask = predicate(train).fillna(False)
        selected = train.loc[mask]
        m = metrics(selected[OUTCOME] - SELECTION_COST_R)
        if name == "BASELINE" or m["trades"] < MIN_TRAIN_TRADES or m["mean_R"] is None:
            continue
        if m["profit_factor"] is None or m["profit_factor"] < 1.05:
            continue
        if m["mean_R"] < (baseline["mean_R"] or 0) + MIN_EDGE_IMPROVEMENT_R:
            continue
        eligible.append((name, m))
    if not eligible:
        return "BASELINE", {"reason": "No candidate cleared training sample, PF and edge-improvement gates", "baseline_train": baseline}
    # Conservative tie-break: prefer more trades, then higher mean; avoids tiny-sample wins.
    eligible.sort(key=lambda x: (x[1]["trades"], x[1]["mean_R"]), reverse=True)
    return eligible[0][0], {"reason": "Selected using training window only", "baseline_train": baseline, "selected_train": eligible[0][1]}


def evaluate(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    data = prepare(frame)
    if data.empty:
        raise ValueError("No eligible replay rows after validation")
    first = data["scan_ts"].min().ceil("D") + pd.Timedelta(days=TRAIN_DAYS)
    last = data["scan_ts"].max()
    folds = []
    oos_parts = []
    fold_start = first
    while fold_start < last:
        fold_end = fold_start + pd.Timedelta(days=TEST_DAYS)
        train_end = fold_start - pd.Timedelta(hours=PURGE_HOURS)
        train_start = train_end - pd.Timedelta(days=TRAIN_DAYS)
        train = data[(data.scan_ts >= train_start) & (data.scan_ts < train_end)]
        test = data[(data.scan_ts >= fold_start) & (data.scan_ts < fold_end)]
        if len(test):
            if len(train) >= MIN_TRAIN_TRADES:
                chosen, selection = select_rule(train)
            else:
                chosen, selection = "BASELINE", {"reason": "Insufficient training rows", "baseline_train": metrics(train[OUTCOME] - SELECTION_COST_R)}
            mask = RULES[chosen](test).fillna(False)
            selected = test.loc[mask].copy()
            selected["fold_start"] = fold_start.isoformat()
            selected["fold_end"] = fold_end.isoformat()
            selected["selected_rule"] = chosen
            oos_parts.append(selected)
            folds.append({
                "fold_start": fold_start.isoformat(),
                "fold_end": fold_end.isoformat(),
                "train_rows": int(len(train)),
                "test_rows": int(len(test)),
                "selected_rule": chosen,
                "selection_reason": selection["reason"],
                "baseline_train_at_selection_cost": selection.get("baseline_train"),
                "selected_train_at_selection_cost": selection.get("selected_train"),
                "oos_selected_trades": int(len(selected)),
            })
        fold_start += pd.Timedelta(days=STEP_DAYS)
    oos = pd.concat(oos_parts, ignore_index=True) if oos_parts else data.iloc[0:0].copy()
    # Each baseline test fold includes every candidate row, including rows excluded by chosen rules.
    test_start = first
    baseline_oos = data[data.scan_ts >= first].copy()
    fold_metrics = []
    for cost in COSTS_R:
        baseline_net = baseline_oos[OUTCOME] - cost
        chosen_net = oos[OUTCOME] - cost
        bm, sm = metrics(baseline_net), metrics(chosen_net)
        fold_means = []
        if not oos.empty:
            for _, group in oos.assign(net= oos[OUTCOME] - cost).groupby("fold_start"):
                if len(group):
                    fold_means.append(float(group["net"].mean()))
        fold_metrics.append({
            "assumed_cost_R": cost,
            **{f"baseline_{k}": v for k, v in bm.items()},
            **{f"walk_forward_selected_{k}": v for k, v in sm.items()},
            "mean_oos_fold_return_R": round(float(np.mean(fold_means)), 5) if fold_means else None,
            "positive_oos_folds_pct": round(float(np.mean(np.array(fold_means) > 0) * 100), 2) if fold_means else None,
        })
    report = {
        "status": "completed",
        "rows": int(len(data)),
        "first_signal_utc": data.scan_ts.min().isoformat(),
        "last_signal_utc": data.scan_ts.max().isoformat(),
        "outcome": OUTCOME,
        "train_days": TRAIN_DAYS,
        "test_days": TEST_DAYS,
        "step_days": STEP_DAYS,
        "purge_hours": PURGE_HOURS,
        "selection_cost_R": SELECTION_COST_R,
        "minimum_training_trades": MIN_TRAIN_TRADES,
        "minimum_edge_improvement_R": MIN_EDGE_IMPROVEMENT_R,
        "predeclared_rules": list(RULES),
        "folds": folds,
        "oos_rows_selected_by_walk_forward_rule": int(len(oos)),
        "baseline_oos_rows": int(len(baseline_oos)),
        "cost_comparison": fold_metrics,
        "live_filter_changed": False,
        "guardrails": [
            "The rule is selected from past training rows only; 24h outcomes crossing the test boundary are purged.",
            "The report is a model-selection diagnostic, not an independent holdout after strategy design.",
            "Candidates are predeclared and intentionally limited; do not add filters based on these OOS results and then reuse the same period as untouched validation.",
            "Returns use Yahoo OHLC proxy outcomes and fixed assumed cost in R; broker spread, slippage, financing, market impact and contract mapping are unavailable.",
            "Signals can remain correlated across symbols and calendar time; positive mean alone is insufficient for live deployment.",
            "No live signal rules are modified by this script.",
        ],
    }
    return pd.DataFrame(folds), pd.DataFrame(fold_metrics), report


def main() -> int:
    source = ROOT / "live-pipeline-replay.csv"
    if not source.exists():
        raise FileNotFoundError(f"Missing {source}; run scripts/replay_live_pipeline.py first")
    folds, costs, report = evaluate(pd.read_csv(source))
    ROOT.mkdir(parents=True, exist_ok=True)
    folds.to_csv(ROOT / "walk-forward-signal-filter-folds.csv", index=False)
    costs.to_csv(ROOT / "walk-forward-signal-filter-costs.csv", index=False)
    (ROOT / "walk-forward-signal-filter-report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))
    print("\nCost comparison:")
    print(costs.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
