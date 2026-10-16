"""Summarize the scheduled live-pipeline replay with cost sensitivity."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(os.getenv("RESEARCH_OUTPUT", "research_data"))
POLICIES = ["tp1_full_R", "tp2_full_R", "half_be_R", "half_sl_R"]
COSTS_R = [0.0, 0.05, 0.10, 0.20]


def metrics(values: pd.Series) -> dict:
    x = pd.to_numeric(values, errors="coerce").dropna()
    if x.empty:
        return {
            "trades": 0, "mean_R": None, "median_R": None,
            "win_rate_pct": None, "profit_factor": None, "max_drawdown_R": None,
        }
    gains = float(x[x > 0].sum())
    losses = float(-x[x < 0].sum())
    equity = x.cumsum()
    drawdown = equity - equity.cummax().clip(lower=0)
    return {
        "trades": int(len(x)),
        "mean_R": round(float(x.mean()), 5),
        "median_R": round(float(x.median()), 5),
        "win_rate_pct": round(float((x > 0).mean() * 100), 2),
        "profit_factor": round(gains / losses, 4) if losses else None,
        "max_drawdown_R": round(float(drawdown.min()), 4),
    }


def analyze(frame: pd.DataFrame):
    rows = []
    for policy in POLICIES:
        for cost in COSTS_R:
            net = pd.to_numeric(frame[policy], errors="coerce") - cost
            rows.append({
                "group_by": "overall", "group": "all", "policy": policy,
                "assumed_round_trip_cost_R": cost, **metrics(net),
            })
            for dimension in ("slot", "symbol", "direction"):
                if dimension not in frame.columns:
                    continue
                for value, group in frame.groupby(dimension, dropna=False):
                    values = pd.to_numeric(group[policy], errors="coerce") - cost
                    rows.append({
                        "group_by": dimension, "group": str(value), "policy": policy,
                        "assumed_round_trip_cost_R": cost, **metrics(values),
                    })
    summary = pd.DataFrame(rows)
    return summary


def main():
    source = ROOT / "live-pipeline-replay.csv"
    if not source.exists():
        raise FileNotFoundError(f"Missing {source}; run scripts/replay_live_pipeline.py first")
    frame = pd.read_csv(source)
    if frame.empty:
        summary = pd.DataFrame()
        summary.to_csv(ROOT / "live-pipeline-summary.csv", index=False)
        report = {"trades": 0, "warning": "No selected, fully matured pipeline signals were available."}
    else:
        frame["scan_ts"] = pd.to_datetime(frame["scan_ts"], utc=True, errors="coerce")
        frame = frame.dropna(subset=["scan_ts"]).sort_values(["scan_ts", "symbol"])
        summary = analyze(frame)
        summary.to_csv(ROOT / "live-pipeline-summary.csv", index=False)
        base = summary[
            (summary["group_by"] == "overall")
            & (summary["assumed_round_trip_cost_R"].isin([0.0, 0.05, 0.10]))
        ]
        report = {
            "trades": int(len(frame)),
            "start_utc": frame["scan_ts"].min().isoformat(),
            "end_utc": frame["scan_ts"].max().isoformat(),
            "overall_cost_sensitivity": base.to_dict(orient="records"),
            "warning": "Research-only. Costs are assumptions, data is Yahoo proxy, and omitted historical news/adaptive snapshots/5m quotes prevent exact production parity.",
        }
    (ROOT / "live-pipeline-summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
