"""Sensitivity grid for the duration-aware selector; research-only."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from scripts.walk_forward_duration_validation import COSTS_R, ROOT, validate

MIN_COUNTS = tuple(int(x) for x in os.getenv("DURATION_ROBUST_MIN_COUNTS", "8,12,16,20").split(",") if x.strip())
MIN_EDGES = tuple(float(x) for x in os.getenv("DURATION_ROBUST_MIN_EDGES_R", "0.02,0.05,0.10").split(",") if x.strip())
COST_R = float(os.getenv("DURATION_ROBUST_COST_R", "0.05"))


def run_grid(trades: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows = []
    for min_count in MIN_COUNTS:
        for min_edge in MIN_EDGES:
            folds, summary, report = validate(
                trades,
                min_train_trades=min_count,
                min_train_edge_r=min_edge,
                costs_r=(COST_R,),
            )
            selected = summary[
                (summary["mode"] == "duration_selector")
                & (summary["assumed_round_trip_cost_R"] == COST_R)
            ] if not summary.empty else pd.DataFrame()
            fold_selected = folds[
                (folds["mode"] == "duration_selector")
                & (folds["assumed_round_trip_cost_R"] == COST_R)
            ] if not folds.empty else pd.DataFrame()
            item = {
                "min_training_trades": min_count,
                "min_training_net_edge_R": min_edge,
                "assumed_cost_R": COST_R,
                "folds": int(report.get("folds", 0)),
                "eligible_groups_mean": round(float(fold_selected["eligible_groups"].mean()), 3)
                    if not fold_selected.empty else 0,
                "trades": int(selected.iloc[0]["trades"]) if not selected.empty else 0,
                "mean_R": float(selected.iloc[0]["mean_R"]) if not selected.empty and pd.notna(selected.iloc[0]["mean_R"]) else None,
                "median_R": float(selected.iloc[0]["median_R"]) if not selected.empty and pd.notna(selected.iloc[0]["median_R"]) else None,
                "profit_factor": float(selected.iloc[0]["profit_factor"]) if not selected.empty and pd.notna(selected.iloc[0]["profit_factor"]) else None,
                "max_drawdown_R": float(selected.iloc[0]["max_drawdown_R"]) if not selected.empty and pd.notna(selected.iloc[0]["max_drawdown_R"]) else None,
                "positive_test_folds_pct": float(selected.iloc[0]["positive_test_folds_pct"]) if not selected.empty else 0.0,
                "worst_fold_mean_R": float(fold_selected["mean_R"].min()) if not fold_selected.empty and fold_selected["mean_R"].notna().any() else None,
                "all_test_folds_positive": bool(
                    not fold_selected.empty
                    and len(fold_selected) == int(report.get("folds", 0))
                    and (fold_selected["mean_R"] > 0).all()
                ),
            }
            rows.append(item)
    result = pd.DataFrame(rows)
    report = {
        "status": "completed" if not result.empty else "insufficient_data",
        "scenarios": len(result),
        "minimum_training_trade_counts": list(MIN_COUNTS),
        "minimum_training_net_edges_R": list(MIN_EDGES),
        "assumed_cost_R": COST_R,
        "selection_rule_varied_without_changing_live_rules": True,
        "interpretation_warning": (
            "Sensitivity analysis is not an independent holdout: scenarios reuse the same historical period. "
            "Do not select the best row and treat it as unbiased performance. Proxy prices and assumed costs "
            "are not broker fills. This report does not authorize live trading."
        ),
    }
    return result, report


def main() -> int:
    source = ROOT / "live-pipeline-replay.csv"
    if not source.exists():
        raise FileNotFoundError(f"Missing {source}; run scripts/replay_live_pipeline.py first")
    result, report = run_grid(pd.read_csv(source))
    ROOT.mkdir(parents=True, exist_ok=True)
    result.to_csv(ROOT / "duration-selector-robustness.csv", index=False)
    (ROOT / "duration-selector-robustness-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    print("\nDuration-selector sensitivity grid:")
    print(result.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
