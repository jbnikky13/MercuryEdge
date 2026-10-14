"""Analyze historical replay with a per-symbol 24h no-overlap rule and cost sensitivity.

This is a research-only postprocessor: it does not change signal generation or live behavior.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(os.getenv("RESEARCH_OUTPUT", "research_data"))
POLICIES = ["tp1_full_R", "tp2_full_R", "half_be_R"]
COSTS_R = [0.0, 0.05, 0.10, 0.20]
COOLDOWN_HOURS = 24


def _metrics(values: pd.Series) -> dict:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return {"trades": 0, "mean_R": None, "median_R": None, "win_rate_pct": None,
                "profit_factor": None, "max_drawdown_R": None}
    gains = values[values > 0].sum()
    losses = -values[values < 0].sum()
    equity = values.cumsum()
    drawdown = equity - equity.cummax().clip(lower=0)
    return {
        "trades": int(len(values)),
        "mean_R": round(float(values.mean()), 5),
        "median_R": round(float(values.median()), 5),
        "win_rate_pct": round(float((values > 0).mean() * 100), 2),
        "profit_factor": round(float(gains / losses), 4) if losses > 0 else None,
        "max_drawdown_R": round(float(drawdown.min()), 4),
    }


def select_non_overlapping(trades: pd.DataFrame, cooldown_hours: int = COOLDOWN_HOURS) -> pd.DataFrame:
    """Keep the earliest signal, then skip same-symbol signals during its 24h horizon."""
    if trades.empty:
        return trades.copy()
    d = trades.copy()
    d["ts"] = pd.to_datetime(d["ts"], utc=True, errors="coerce")
    d = d.dropna(subset=["ts"]).sort_values(["symbol", "ts"]).reset_index(drop=True)
    accepted = []
    cooldown = pd.Timedelta(hours=cooldown_hours)
    for _, group in d.groupby("symbol", sort=False):
        next_allowed = None
        for idx, row in group.iterrows():
            if next_allowed is None or row["ts"] >= next_allowed:
                accepted.append(idx)
                next_allowed = row["ts"] + cooldown
    out = d.loc[accepted].sort_values(["ts", "symbol"]).reset_index(drop=True)
    out["cooldown_hours"] = cooldown_hours
    return out


def analyze(trades: pd.DataFrame):
    selected = select_non_overlapping(trades)
    summaries = []
    for policy in POLICIES:
        for cost in COSTS_R:
            net = pd.to_numeric(selected[policy], errors="coerce") - cost
            summaries.append({"policy": policy, "assumed_round_trip_cost_R": cost, **_metrics(net)})
    overall = pd.DataFrame(summaries)

    by_symbol = []
    for symbol, group in selected.groupby("symbol"):
        for policy in POLICIES:
            for cost in COSTS_R:
                net = pd.to_numeric(group[policy], errors="coerce") - cost
                by_symbol.append({"symbol": symbol, "policy": policy,
                                  "assumed_round_trip_cost_R": cost, **_metrics(net)})
    symbol_summary = pd.DataFrame(by_symbol)

    periods = []
    chronological = selected.sort_values("ts").reset_index(drop=True)
    if not chronological.empty:
        chronological["period"] = pd.qcut(
            chronological.index + 1, q=min(4, len(chronological)),
            labels=False, duplicates="drop"
        )
        for period, group in chronological.groupby("period", observed=True):
            for policy in POLICIES:
                for cost in COSTS_R:
                    net = pd.to_numeric(group[policy], errors="coerce") - cost
                    periods.append({
                        "chronological_period": int(period) + 1,
                        "period_start_utc": group["ts"].min().isoformat(),
                        "period_end_utc": group["ts"].max().isoformat(),
                        "policy": policy, "assumed_round_trip_cost_R": cost, **_metrics(net),
                    })
    return selected, overall, symbol_summary, pd.DataFrame(periods)


def main() -> int:
    source = ROOT / "replayed-signals.csv"
    if not source.exists():
        raise FileNotFoundError(f"Missing {source}; run scripts/research_historical.py first")
    trades = pd.read_csv(source)
    selected, overall, by_symbol, by_period = analyze(trades)
    selected.to_csv(ROOT / "independent-trades.csv", index=False)
    overall.to_csv(ROOT / "independent-summary.csv", index=False)
    by_symbol.to_csv(ROOT / "independent-by-symbol.csv", index=False)
    by_period.to_csv(ROOT / "independent-by-period.csv", index=False)
    report = {
        "input_signals": int(len(trades)),
        "non_overlapping_signals": int(len(selected)),
        "selection_rule": "Keep first signal per symbol; skip further same-symbol signals for 24 hours",
        "cross_symbol_overlap_removed": False,
        "cost_sensitivity_R_per_trade": COSTS_R,
        "costs_are_scenarios_not_measured_broker_costs": True,
        "warning": "Research sensitivity only. Same-symbol overlap is reduced, but cross-market correlation, broker mapping, and actual transaction costs remain unverified.",
    }
    (ROOT / "independent-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("\nOverall summary:")
    print(overall.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
