"""Audit whether replay data contains genuine ex-ante duration candidates.

This deliberately does not infer intended duration from future outcomes. The current
pipeline uses one ATR-based entry/SL/TP geometry and assigns a preferred label from
matured historical analogue hit rates; this audit makes that limitation explicit.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(os.getenv("RESEARCH_OUTPUT", "research_data"))
DURATION_LABELS = ("INTRADAY_0_24H", "SWING_24_72H", "POSITION_3_5D")
FUTURE_OUTCOME_FIELDS = {
    "actual_holding_window", "tp1_time_hours", "tp2_time_hours", "stop_time_hours",
    "outcome_24h", "outcome_5d", "tp1_full_R_24h", "tp1_full_R_5d",
}


def audit(trades: pd.DataFrame) -> dict:
    required = {"scan_ts", "symbol", "direction", "holding_period"}
    missing = sorted(required - set(trades.columns))
    if missing:
        return {
            "status": "invalid_input",
            "missing_columns": missing,
            "input_rows": int(len(trades)),
            "future_outcomes_used_for_selection": False,
        }

    labels = trades["holding_period"].fillna("MISSING").astype(str)
    counts = {label: int((labels == label).sum()) for label in DURATION_LABELS}
    other = labels[~labels.isin(DURATION_LABELS)].value_counts().to_dict()
    populated = [label for label, count in counts.items() if count > 0]
    distinct_durations = len(populated)
    has_exit_geometry = {"entry", "sl", "tp1", "tp2"}.issubset(trades.columns)
    geometry_varies = False
    if has_exit_geometry and distinct_durations > 1:
        geometry = trades.assign(_duration=labels).groupby("_duration")[["entry", "sl", "tp1", "tp2"]].median()
        geometry_varies = len(geometry.drop_duplicates()) > 1

    # The selection inputs are point-in-time analogue fields. Future outcome columns
    # are intentionally excluded; their presence is expected only for grading.
    selection_fields = ["scan_ts", "symbol", "direction", "score", "historical_win_rate_1d_pct",
                        "historical_win_rate_3d_pct", "historical_win_rate_5d_pct", "holding_period"]
    available_selection_fields = [field for field in selection_fields if field in trades.columns]
    future_fields_present = sorted(FUTURE_OUTCOME_FIELDS.intersection(trades.columns))
    actual_window_is_selection_field = "actual_holding_window" in available_selection_fields

    if trades.empty:
        status = "no_trades"
    elif distinct_durations >= 2 and geometry_varies:
        status = "multiple_duration_labels_and_exit_geometries"
    elif distinct_durations >= 2:
        status = "multiple_labels_shared_exit_geometry"
    else:
        status = "single_duration_label_only"

    return {
        "status": status,
        "input_rows": int(len(trades)),
        "duration_label_counts": counts,
        "other_or_missing_labels": {str(k): int(v) for k, v in other.items()},
        "distinct_duration_labels_present": distinct_durations,
        "exit_geometry_fields_present": has_exit_geometry,
        "exit_geometry_varies_by_duration": geometry_varies,
        "historical_horizon_selection_is_ex_ante": True,
        "historical_horizon_selection_note": (
            "holding_period is assigned from fully matured historical analogue hit rates, "
            "not from the trade's future realized holding time."
        ),
        "future_outcome_fields_present_for_grading_only": future_fields_present,
        "future_actual_holding_window_used_as_selection_input": actual_window_is_selection_field,
        "claim_limit": (
            "Multiple distinct duration-specific trade strategies are not established unless "
            "duration labels and entry/exit geometry are independently generated and validated."
        ),
        "research_only": True,
    }


def main() -> int:
    source = ROOT / "live-pipeline-replay.csv"
    if not source.exists():
        raise FileNotFoundError(f"Missing {source}; run scripts/replay_live_pipeline.py first")
    result = audit(pd.read_csv(source))
    ROOT.mkdir(parents=True, exist_ok=True)
    target = ROOT / "duration-candidate-audit.json"
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    # This is a diagnostic, not a CI failure: a single-horizon result is useful
    # evidence about a research limitation and should not hide other artifacts.
    return 0 if result["status"] != "invalid_input" else 1


if __name__ == "__main__":
    raise SystemExit(main())
