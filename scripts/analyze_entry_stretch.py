"""Evaluate whether entry stretch predicts weaker historical outcomes.

Research-only diagnostic. It reports predefined ATR-distance buckets and fixed
stretch caps against the same selected entries; it never changes live selection.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("research_data")
COSTS_R = (0.0, 0.05, 0.10, 0.15)
BUCKETS = (
    ("0_to_0.5_ATR", 0.0, 0.5),
    ("0.5_to_1.0_ATR", 0.5, 1.0),
    ("1.0_to_1.5_ATR", 1.0, 1.5),
    ("1.5_to_2.0_ATR", 1.5, 2.0),
    ("2.0_plus_ATR", 2.0, float("inf")),
)
CAPS_ATR = (1.0, 1.5, 2.0)
MIN_BUCKET_TRADES = 20


def _pf(values: pd.Series) -> float | None:
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / losses


def _metrics(values: pd.Series) -> dict:
    x = pd.to_numeric(values, errors="coerce").dropna()
    if x.empty:
        return {"trades": 0, "mean_R": None, "median_R": None, "win_rate_pct": None, "profit_factor": None}
    return {
        "trades": int(len(x)),
        "mean_R": round(float(x.mean()), 5),
        "median_R": round(float(x.median()), 5),
        "win_rate_pct": round(float((x > 0).mean() * 100), 2),
        "profit_factor": round(_pf(x), 4) if _pf(x) is not None and np.isfinite(_pf(x)) else _pf(x),
    }


def analyze(trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    required = {"scan_ts", "symbol", "entry_stretch_atr", "tp1_full_R_24h"}
    missing = sorted(required - set(trades.columns))
    if missing:
        raise ValueError(f"Replay data missing columns: {missing}")
    data = trades.copy()
    data["scan_ts"] = pd.to_datetime(data["scan_ts"], utc=True, errors="coerce")
    data["entry_stretch_atr"] = pd.to_numeric(data["entry_stretch_atr"], errors="coerce")
    data["tp1_full_R_24h"] = pd.to_numeric(data["tp1_full_R_24h"], errors="coerce")
    data = data.dropna(subset=["scan_ts", "entry_stretch_atr", "tp1_full_R_24h"])
    data = data[data["entry_stretch_atr"] >= 0].copy()
    data["stretch_bucket"] = pd.cut(
        data["entry_stretch_atr"],
        bins=[0.0, 0.5, 1.0, 1.5, 2.0, float("inf")],
        labels=[item[0] for item in BUCKETS],
        right=False,
        include_lowest=True,
    )
    bucket_rows = []
    for label, lower, upper in BUCKETS:
        group = data[(data.entry_stretch_atr >= lower) & (data.entry_stretch_atr < upper)]
        for cost in COSTS_R:
            bucket_rows.append({
                "stretch_bucket": label,
                "lower_atr_inclusive": lower,
                "upper_atr_exclusive": upper if np.isfinite(upper) else None,
                "assumed_cost_R": cost,
                **_metrics(group["tp1_full_R_24h"] - cost),
            })
    buckets = pd.DataFrame(bucket_rows)

    cap_rows = []
    for cap in CAPS_ATR:
        group = data[data.entry_stretch_atr <= cap]
        excluded = data[data.entry_stretch_atr > cap]
        for cost in COSTS_R:
            selected_metrics = _metrics(group["tp1_full_R_24h"] - cost)
            excluded_metrics = _metrics(excluded["tp1_full_R_24h"] - cost)
            cap_rows.append({
                "max_entry_stretch_atr": cap,
                "assumed_cost_R": cost,
                **{f"selected_{k}": v for k, v in selected_metrics.items()},
                **{f"excluded_{k}": v for k, v in excluded_metrics.items()},
            })
    caps = pd.DataFrame(cap_rows)

    at_cost = data["tp1_full_R_24h"] - 0.10
    monthly = data.assign(net_R=at_cost, month=data.scan_ts.dt.to_period("M").astype(str))
    monthly_rows = []
    for month, group in monthly.groupby("month"):
        monthly_rows.append({"month": month, **_metrics(group.net_R)})
    monthly_table = pd.DataFrame(monthly_rows)

    report = {
        "status": "completed" if len(data) else "insufficient_data",
        "eligible_rows": int(len(data)),
        "missing_or_invalid_stretch_or_outcome_rows": int(len(trades) - len(data)),
        "outcome_column": "tp1_full_R_24h",
        "entry_stretch_definition": "absolute distance between entry and last completed hourly EMA20, divided by last completed hourly ATR",
        "cost_scenarios_R": list(COSTS_R),
        "predefined_caps_ATR": list(CAPS_ATR),
        "minimum_bucket_trades_for_interpretation": MIN_BUCKET_TRADES,
        "caps_are_diagnostic_only": True,
        "live_filter_changed": False,
        "cost_0_10R_overall": _metrics(data["tp1_full_R_24h"] - 0.10),
        "monthly_net_at_0_10R": monthly_rows,
        "interpretation_guardrails": [
            "Buckets are descriptive and not independent samples; markets and weeks may be correlated.",
            "A cap is not recommended from this report alone, especially when selected count is below the minimum.",
            "The 24-hour outcome is a Yahoo OHLC proxy and excludes broker spread, slippage, funding and contract mapping.",
            "This is an analysis of the current selected entries, not a causal proof that stretch causes losses.",
        ],
    }
    return buckets, caps, report


def main() -> int:
    source = ROOT / "live-pipeline-replay.csv"
    if not source.exists():
        raise FileNotFoundError(f"Missing {source}; run scripts/replay_live_pipeline.py first")
    trades = pd.read_csv(source)
    buckets, caps, report = analyze(trades)
    ROOT.mkdir(parents=True, exist_ok=True)
    buckets.to_csv(ROOT / "entry-stretch-bucket-analysis.csv", index=False)
    caps.to_csv(ROOT / "entry-stretch-cap-comparison.csv", index=False)
    (ROOT / "entry-stretch-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("\nBucket analysis:")
    print(buckets[buckets.assumed_cost_R.isin([0.05, 0.10])].to_string(index=False))
    print("\nDiagnostic caps:")
    print(caps[caps.assumed_cost_R.isin([0.05, 0.10])].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
