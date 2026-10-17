"""Exploratory duration-specific exit-geometry replay on fixed entry signals.

This creates separate ATR-risk-scaled exit candidates from already-generated
entry/direction signals, then grades each candidate only on its matching future
hourly window. It is an ablation, not a live rule change or proof of edge.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from scripts.research_historical import _settle_one

ROOT = Path(os.getenv("RESEARCH_OUTPUT", "research_data"))
VARIANTS = {
    "INTRADAY_0_24H": {"bars": 24, "risk_multiplier": 1.0},
    "SWING_24_72H": {"bars": 72, "risk_multiplier": 1.5},
    "POSITION_3_5D": {"bars": 120, "risk_multiplier": 2.0},
}
COSTS_R = (0.0, 0.05, 0.10, 0.15, 0.20)


def build_variant(signal: dict, label: str) -> dict:
    """Build a duration-specific exit geometry from entry-time fields only."""
    if label not in VARIANTS:
        raise ValueError(f"Unknown duration variant: {label}")
    entry = float(signal["entry"])
    base_risk = abs(entry - float(signal["sl"]))
    if base_risk <= 0:
        raise ValueError("Signal stop distance must be positive")
    side = 1 if str(signal["direction"]).upper() == "BUY" else -1
    if str(signal["direction"]).upper() not in {"BUY", "SELL"}:
        raise ValueError("direction must be BUY or SELL")
    spec = VARIANTS[label]
    risk = base_risk * spec["risk_multiplier"]
    return {
        **signal,
        "holding_period": label,
        "variant_horizon_bars": spec["bars"],
        "risk_multiplier": spec["risk_multiplier"],
        "sl": entry - side * risk,
        "tp1": entry + side * risk * 1.15,
        "tp2": entry + side * risk * 2.25,
        "variant_risk": risk,
    }


def _summary(values: pd.Series) -> dict:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return {"trades": 0, "mean_net_R": None, "win_rate_pct": None, "profit_factor": None}
    gains = float(clean[clean > 0].sum())
    losses = float(-clean[clean < 0].sum())
    return {
        "trades": int(len(clean)),
        "mean_net_R": round(float(clean.mean()), 5),
        "win_rate_pct": round(float((clean > 0).mean() * 100), 2),
        "profit_factor": round(gains / losses, 4) if losses else (None if gains == 0 else "inf"),
    }


def replay_variants(trades: pd.DataFrame, root: Path = ROOT) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    required = {"scan_ts", "symbol", "direction", "entry", "sl"}
    missing = sorted(required - set(trades.columns))
    if missing:
        raise ValueError(f"Replay input missing columns: {missing}")
    rows = []
    for signal in trades.to_dict("records"):
        ts = pd.Timestamp(signal["scan_ts"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        path = root / "hourly" / f"{signal['symbol']}.csv"
        if not path.exists():
            continue
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        frame.index = pd.to_datetime(frame.index, utc=True)
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        frame = frame.dropna(subset=["Open", "High", "Low", "Close"])
        future = frame[frame.index >= ts.ceil("h")]
        for label, spec in VARIANTS.items():
            variant = build_variant(signal, label)
            window = future.iloc[:spec["bars"]]
            if len(window) < spec["bars"]:
                continue
            settled = _settle_one(pd.Series({
                "direction": variant["direction"],
                "entry": float(variant["entry"]),
                "risk": float(variant["variant_risk"]),
                "sl": float(variant["sl"]),
                "tp1": float(variant["tp1"]),
                "tp2": float(variant["tp2"]),
            }), window)
            rows.append({
                "scan_ts": ts.isoformat(), "symbol": signal["symbol"],
                "direction": signal["direction"], "score": signal.get("score"),
                "holding_period": label, "horizon_bars": spec["bars"],
                "risk_multiplier": spec["risk_multiplier"],
                "entry": variant["entry"], "sl": variant["sl"],
                "tp1": variant["tp1"], "tp2": variant["tp2"],
                "outcome": settled["outcome"],
                "tp1_hit": settled["tp1_hit"],
                "tp1_full_R": settled["tp1_full_R"],
                "tp2_full_R": settled["tp2_full_R"],
                "half_be_R": settled["half_be_R"],
                "half_sl_R": settled["half_sl_R"],
            })
    results = pd.DataFrame(rows)
    if results.empty:
        summary = pd.DataFrame(columns=["holding_period", "assumed_cost_R", "trades", "mean_net_R", "win_rate_pct", "profit_factor"])
    else:
        summaries = []
        for label, group in results.groupby("holding_period", sort=False):
            for cost in COSTS_R:
                values = group["tp1_full_R"] - cost
                summaries.append({
                    "holding_period": label, "assumed_cost_R": cost, **_summary(values),
                    "risk_multiplier": VARIANTS[label]["risk_multiplier"],
                    "horizon_bars": VARIANTS[label]["bars"],
                })
        summary = pd.DataFrame(summaries)
    report = {
        "status": "completed" if not results.empty else "no_matured_variants",
        "input_signals": int(len(trades)),
        "variant_rows": int(len(results)),
        "duration_variants": VARIANTS,
        "exit_geometry": "ATR-risk proxy inferred from baseline stop distance; TP1=1.15R and TP2=2.25R",
        "grading": "Each variant graded independently over its declared future hourly-bar horizon; stop-first tie break inherited from historical replay.",
        "cost_scenarios_R": list(COSTS_R),
        "selection_uses_future_outcomes": False,
        "selection_policy": "No variant is selected in this experiment; this is a parallel exit-geometry ablation.",
        "limitations": [
            "Entry signals are inherited from the current pipeline, so this does not generate independent entry strategies.",
            "Risk multipliers are research hypotheses, not fitted or validated live parameters.",
            "Hourly Yahoo Finance OHLC proxy; no broker fills, spread, slippage, funding or contract mapping.",
            "Overlapping entries and correlated markets remain possible; summary metrics are descriptive, not proof of profitability.",
        ],
        "research_only": True,
    }
    root.mkdir(parents=True, exist_ok=True)
    results.to_csv(root / "duration-variant-trades.csv", index=False)
    summary.to_csv(root / "duration-variant-cost-summary.csv", index=False)
    (root / "duration-variant-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return results, summary, report


def main() -> int:
    source = ROOT / "live-pipeline-replay.csv"
    if not source.exists():
        raise FileNotFoundError(f"Missing {source}; run scripts/replay_live_pipeline.py first")
    trades = pd.read_csv(source)
    results, summary, report = replay_variants(trades)
    print(json.dumps(report, indent=2))
    print(summary.to_string(index=False) if not summary.empty else "No mature duration variants.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
