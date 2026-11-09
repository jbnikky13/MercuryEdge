"""Research-only comparison of fixed Deriv synthetic strategy candidates.

This module does not modify production signals, market configuration, Telegram,
or execution. Candidate rules are fixed before each chronological test window;
selection uses training data only and test outcomes are never used for tuning.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from mercuryedge.analysis import add_indicators, analyze
from mercuryedge.deriv_data import DerivPublicClient
from scripts.research_historical import _settle_one

DEFAULT_SYMBOLS = ("R_10", "R_25", "R_50", "R_75", "R_100")
STRATEGIES = ("current_rules", "trend_pullback", "donchian_breakout", "ema_reclaim")
DEFAULT_COSTS_R = (0.0, 0.05, 0.10)


def _candidate_direction(strategy: str, row: pd.Series, previous: pd.Series) -> str | None:
    """Evaluate a fixed candidate using only the current and previous completed bars."""
    up = row.EMA20 > row.EMA50 > row.EMA200
    down = row.EMA20 < row.EMA50 < row.EMA200
    bullish_bar = row.Close > row.Open
    bearish_bar = row.Close < row.Open

    if strategy == "trend_pullback":
        buy = (up and row.Low <= row.EMA20 + 0.10 * row.ATR
               and row.Close > row.EMA20 and bullish_bar
               and 48 <= row.RSI <= 68 and row.MACD > row.MACD_SIGNAL)
        sell = (down and row.High >= row.EMA20 - 0.10 * row.ATR
                and row.Close < row.EMA20 and bearish_bar
                and 32 <= row.RSI <= 52 and row.MACD < row.MACD_SIGNAL)
    elif strategy == "donchian_breakout":
        buy = (row.Close > row.ROLL_HIGH and up and bullish_bar and 52 <= row.RSI <= 75)
        sell = (row.Close < row.ROLL_LOW and down and bearish_bar and 25 <= row.RSI <= 48)
    elif strategy == "ema_reclaim":
        buy = (up and previous.Close <= previous.EMA20 and row.Close > row.EMA20
               and 50 <= row.RSI <= 68 and row.MACD_HIST > previous.MACD_HIST)
        sell = (down and previous.Close >= previous.EMA20 and row.Close < row.EMA20
                and 32 <= row.RSI <= 50 and row.MACD_HIST < previous.MACD_HIST)
    else:
        raise ValueError(f"Unknown candidate strategy: {strategy}")

    if buy:
        return "BUY"
    if sell:
        return "SELL"
    return None


def build_candidate_trades(
    frame: pd.DataFrame, symbol: str, horizon: int = 24, warmup: int = 220
) -> pd.DataFrame:
    """Build matured outcomes for the current rules and three fixed alternatives."""
    if horizon < 1 or warmup < 220:
        raise ValueError("horizon must be positive and warmup must be at least 220")
    enriched = add_indicators(frame)
    if len(enriched) <= warmup + horizon:
        return pd.DataFrame()

    atr_pct = enriched.ATR / enriched.Close.replace(0, np.nan)
    vol_median = atr_pct.rolling(120, min_periods=30).median()
    rows: list[dict] = []
    for index in range(warmup, len(enriched) - horizon):
        row = enriched.iloc[index]
        previous = enriched.iloc[index - 1]
        history = enriched.iloc[: index + 1]
        for strategy in STRATEGIES:
            if strategy == "current_rules":
                setup = analyze(history)
                direction = setup["direction"] if setup else None
            else:
                direction = _candidate_direction(strategy, row, previous)
            if direction is None:
                continue

            entry = float(row.Close)
            risk = float(row.ATR) * 1.25
            if not np.isfinite(risk) or risk <= 0:
                continue
            side = 1.0 if direction == "BUY" else -1.0
            signal = pd.Series({
                "direction": direction, "entry": entry, "risk": risk,
                "sl": entry - side * risk,
                "tp1": entry + side * risk * 1.15,
                "tp2": entry + side * risk * 2.25,
            })
            settled = _settle_one(signal, enriched.iloc[index + 1:index + 1 + horizon])
            timestamp = enriched.index[index]
            median = vol_median.iloc[index]
            rows.append({
                "strategy": strategy, "symbol": symbol,
                "ts": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
                "direction": direction,
                "rsi": float(row.RSI),
                "atr_pct": float(atr_pct.iloc[index]) if pd.notna(atr_pct.iloc[index]) else np.nan,
                "volatility_regime": ("HIGHER_VOL" if pd.notna(median) and atr_pct.iloc[index] >= median
                                      else "LOWER_VOL" if pd.notna(median) else "UNKNOWN"),
                "ema_spread_atr": float((row.EMA20 - row.EMA50) / row.ATR),
                "entry_stretch_atr": float(abs(row.Close - row.EMA20) / row.ATR),
                "candle_body_atr": float(abs(row.Close - row.Open) / row.ATR),
                "entry": entry, "risk": risk,
                **settled,
            })
    return pd.DataFrame(rows)


def _metrics(values: pd.Series) -> dict:
    x = pd.to_numeric(values, errors="coerce").dropna()
    if x.empty:
        return {"trades": 0, "mean_R": None, "median_R": None, "win_rate_pct": None,
                "profit_factor": None, "max_drawdown_R": None}
    gains = float(x[x > 0].sum())
    losses = float(-x[x < 0].sum())
    equity = x.cumsum()
    drawdown = equity - equity.cummax().clip(lower=0)
    return {
        "trades": int(len(x)), "mean_R": round(float(x.mean()), 5),
        "median_R": round(float(x.median()), 5),
        "win_rate_pct": round(float((x > 0).mean() * 100), 2),
        "profit_factor": round(gains / losses, 4) if losses > 0 else (None if gains == 0 else float("inf")),
        "max_drawdown_R": round(float(drawdown.min()), 4),
    }


def _non_overlapping(trades: pd.DataFrame, horizon_hours: int) -> pd.DataFrame:
    """Suppress overlap within each independent strategy/symbol stream."""
    if trades.empty:
        return trades.copy()
    data = trades.copy()
    data["ts"] = pd.to_datetime(data.ts, utc=True, errors="coerce")
    data = data.dropna(subset=["ts", "strategy", "symbol", "direction", "tp1_full_R"])
    data = data.sort_values(["strategy", "symbol", "ts"]).reset_index(drop=True)
    accepted: list[int] = []
    cooldown = pd.Timedelta(hours=horizon_hours)
    for _, group in data.groupby(["strategy", "symbol"], sort=False):
        next_allowed = None
        for idx, row in group.iterrows():
            if next_allowed is None or row.ts >= next_allowed:
                accepted.append(idx)
                next_allowed = row.ts + cooldown
    return data.loc[accepted].sort_values(["ts", "strategy", "symbol"]).reset_index(drop=True)


def walk_forward_candidates(
    trades: pd.DataFrame, train_days: int = 90, test_days: int = 30,
    step_days: int = 30, horizon_hours: int = 24, min_train_trades: int = 20,
    selection_cost_r: float = 0.05, min_train_edge_r: float = 0.02,
    costs_r: tuple[float, ...] = DEFAULT_COSTS_R,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Evaluate each strategy independently with chronological train/test folds."""
    if min(train_days, test_days, step_days, min_train_trades) < 1 or horizon_hours < 0:
        raise ValueError("window lengths and minimum trades must be positive; horizon cannot be negative")
    required = {"strategy", "symbol", "direction", "ts", "tp1_full_R"}
    missing = required - set(trades.columns)
    if missing:
        raise ValueError(f"Missing required candidate columns: {sorted(missing)}")
    data = trades.copy()
    data["ts"] = pd.to_datetime(data.ts, utc=True, errors="coerce")
    data["tp1_full_R"] = pd.to_numeric(data.tp1_full_R, errors="coerce")
    data = data.dropna(subset=list(required)).sort_values(["ts", "strategy", "symbol"])
    data = _non_overlapping(data, horizon_hours)
    fold_rows: list[dict] = []
    oos_rows: list[dict] = []

    for strategy, sample in data.groupby("strategy", sort=True):
        earliest, latest = sample.ts.min(), sample.ts.max()
        test_start = earliest + pd.Timedelta(days=train_days)
        fold = 0
        while test_start <= latest:
            train_start = test_start - pd.Timedelta(days=train_days)
            train_end = test_start - pd.Timedelta(hours=horizon_hours)
            test_end = test_start + pd.Timedelta(days=test_days)
            train = sample[(sample.ts >= train_start) & (sample.ts < train_end)]
            test = sample[(sample.ts >= test_start) & (sample.ts < test_end)].copy()
            if test.empty:
                test_start += pd.Timedelta(days=step_days)
                continue
            fold += 1
            eligible: set[tuple[str, str]] = set()
            for (symbol, direction), group in train.groupby(["symbol", "direction"]):
                mean_net = float(group.tp1_full_R.mean()) - selection_cost_r
                if len(group) >= min_train_trades and mean_net >= min_train_edge_r:
                    eligible.add((str(symbol), str(direction)))
            test["selector_eligible"] = [
                (str(s), str(d)) in eligible for s, d in zip(test.symbol, test.direction)
            ]
            for mode, part in (("all_candidate_signals", test),
                               ("training_selected_groups", test[test.selector_eligible])):
                for cost in costs_r:
                    net = part.tp1_full_R.astype(float) - cost
                    fold_rows.append({
                        "strategy": strategy, "fold": fold, "mode": mode,
                        "assumed_cost_R": cost, "train_trades": int(len(train)),
                        "eligible_groups": len(eligible), **_metrics(net),
                    })
                    for _, row in part.iterrows():
                        oos_rows.append({
                            "strategy": strategy, "fold": fold, "symbol": row.symbol,
                            "direction": row.direction, "ts": row.ts.isoformat(),
                            "mode": mode, "assumed_cost_R": cost,
                            "net_R": float(row.tp1_full_R) - cost,
                        })
            test_start += pd.Timedelta(days=step_days)

    folds = pd.DataFrame(fold_rows)
    oos = pd.DataFrame(oos_rows)
    if oos.empty:
        summary = pd.DataFrame()
        breakdown = pd.DataFrame()
    else:
        summary_rows = []
        for (strategy, mode, cost), group in oos.groupby(["strategy", "mode", "assumed_cost_R"]):
            summary_rows.append({
                "strategy": strategy, "mode": mode, "assumed_cost_R": cost,
                **_metrics(group.sort_values(["ts", "symbol", "fold"]).net_R),
                "positive_folds": int((group.groupby("fold").net_R.mean() > 0).sum()),
                "test_folds": int(group.fold.nunique()),
            })
        summary = pd.DataFrame(summary_rows)
        breakdown_rows = []
        for (strategy, mode, symbol, direction, cost), group in oos.groupby(
            ["strategy", "mode", "symbol", "direction", "assumed_cost_R"]
        ):
            breakdown_rows.append({
                "strategy": strategy, "mode": mode, "symbol": symbol,
                "direction": direction, "assumed_cost_R": cost,
                **_metrics(group.sort_values(["ts", "fold"]).net_R),
                "positive_folds": int((group.groupby("fold").net_R.mean() > 0).sum()),
                "test_folds": int(group.fold.nunique()),
            })
        breakdown = pd.DataFrame(breakdown_rows)

    report = {
        "status": "completed" if not folds.empty else "insufficient_data",
        "candidate_strategies": list(STRATEGIES),
        "input_candidate_trades": int(len(trades)),
        "non_overlapping_candidate_trades": int(len(data)),
        "train_days": train_days, "test_days": test_days, "step_days": step_days,
        "outcome_horizon_hours": horizon_hours,
        "training_boundary_purge_hours": horizon_hours,
        "minimum_training_trades_per_symbol_direction": min_train_trades,
        "selection_cost_R": selection_cost_r, "minimum_training_edge_R": min_train_edge_r,
        "evaluation_cost_scenarios_R": list(costs_r),
        "selection_uses_training_data_only": True,
        "test_windows_are_chronological": True,
        "production_rules_changed": False, "live_signals_enabled": False,
        "warning": (
            "Research-only OHLC replay, not broker fills. Cost scenarios are assumptions, not measured Deriv costs. "
            "Candidate rules are fixed, but comparing multiple strategies creates selection risk; any apparent edge "
            "requires fresh untouched data, contract-specific execution checks, and paper trading."
        ),
    }
    return folds, summary, breakdown, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only Deriv synthetic strategy candidate lab")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--count", type=int, default=5000)
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--train-days", type=int, default=90)
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument("--step-days", type=int, default=30)
    args = parser.parse_args()
    if min(args.count, args.horizon, args.train_days, args.test_days, args.step_days) < 1:
        parser.error("count, horizon, and window lengths must be positive")

    requested = [x.strip() for x in args.symbols.split(",") if x.strip()]
    client = DerivPublicClient(timeout=25)
    available = {client.symbol_code(item) for item in client.synthetic_symbols()}
    unknown = [symbol for symbol in requested if symbol not in available]
    if unknown:
        parser.error(f"Symbols are not active Deriv synthetics: {', '.join(unknown)}")

    print("MERCURYEDGE DERIV STRATEGY LAB — RESEARCH ONLY / NOT LIVE SIGNALS")
    print(f"Symbols={requested} candles={args.count} horizon={args.horizon}h")
    print("Fixed candidates: " + ", ".join(STRATEGIES))
    print("No Telegram delivery, order placement, or production configuration changes.")
    client_frames = []
    for symbol in requested:
        raw = client.candles(symbol, count=args.count, granularity=3600)
        frame = raw.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})
        frame["Volume"] = 0.0
        frame = frame[["Open", "High", "Low", "Close", "Volume"]].dropna()
        candidate = build_candidate_trades(frame, symbol, horizon=args.horizon)
        print(f"{symbol}: candles={len(frame)} candidate_trades={len(candidate)}")
        if not candidate.empty:
            client_frames.append(candidate)

    output = Path(os.getenv("RESEARCH_OUTPUT", "research_data/deriv-strategy-lab"))
    output.mkdir(parents=True, exist_ok=True)
    if not client_frames:
        report = {"status": "insufficient_data", "reason": "No candidate trades matured."}
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0

    all_trades = pd.concat(client_frames, ignore_index=True)
    folds, summary, breakdown, report = walk_forward_candidates(
        all_trades, train_days=args.train_days, test_days=args.test_days,
        step_days=args.step_days, horizon_hours=args.horizon,
    )
    all_trades.to_csv(output / "candidate-trades.csv", index=False)
    folds.to_csv(output / "fold-results.csv", index=False)
    summary.to_csv(output / "strategy-summary.csv", index=False)
    breakdown.to_csv(output / "symbol-direction-breakdown.csv", index=False)
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("\nStrategy summary:")
    print(summary.to_string(index=False) if not summary.empty else "No eligible test windows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
