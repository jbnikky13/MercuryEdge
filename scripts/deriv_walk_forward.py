"""Research-only chronological Deriv synthetic walk-forward validation.

Uses the current MercuryEdge signal rules and the same conservative hourly
settlement model as historical research. Never sends Telegram messages,
places orders, or changes production market configuration.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd

from mercuryedge.analysis import add_indicators, analyze
from mercuryedge.deriv_data import DerivPublicClient
from scripts.research_historical import _settle_one
from scripts.walk_forward_validation import walk_forward

DEFAULT_SYMBOLS = ("R_10", "R_25", "R_50", "R_75", "R_100")
DEFAULT_TRAIN_DAYS = 90
DEFAULT_TEST_DAYS = 30
DEFAULT_STEP_DAYS = 30
DEFAULT_COSTS_R = (0.0, 0.05, 0.10)


def build_trade_rows(
    frame: pd.DataFrame,
    symbol: str,
    horizon: int = 24,
    warmup: int = 220,
) -> pd.DataFrame:
    """Create matured, timestamped R-multiple outcomes without future leakage."""
    if horizon < 1 or warmup < 220:
        raise ValueError("horizon must be positive and warmup must be at least 220")
    enriched = add_indicators(frame)
    if len(enriched) <= warmup + horizon:
        return pd.DataFrame()

    rows: list[dict] = []
    for index in range(warmup, len(enriched) - horizon):
        history = enriched.iloc[: index + 1]
        setup = analyze(history)
        if not setup:
            continue

        future = enriched.iloc[index + 1 : index + 1 + horizon]
        risk = abs(float(setup["entry"]) - float(setup["sl"]))
        if risk <= 0:
            continue
        settlement_input = pd.Series({
            "direction": setup["direction"],
            "entry": float(setup["entry"]),
            "risk": risk,
            "sl": float(setup["sl"]),
            "tp1": float(setup["tp1"]),
            "tp2": float(setup["tp2"]),
        })
        settled = _settle_one(settlement_input, future)
        timestamp = enriched.index[index]
        rows.append({
            "symbol": symbol,
            "ts": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
            "direction": setup["direction"],
            "outcome": settled["outcome"],
            "tp1_full_R": float(settled["tp1_full_R"]),
            "tp2_full_R": float(settled["tp2_full_R"]),
        })
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research-only Deriv synthetic chronological walk-forward validation"
    )
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--count", type=int, default=5000)
    parser.add_argument("--granularity", type=int, default=3600)
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    parser.add_argument("--test-days", type=int, default=DEFAULT_TEST_DAYS)
    parser.add_argument("--step-days", type=int, default=DEFAULT_STEP_DAYS)
    parser.add_argument("--min-train-trades", type=int, default=20)
    args = parser.parse_args()

    if args.granularity != 3600:
        parser.error("This first Deriv walk-forward version is calibrated for 1-hour candles only")
    if min(args.train_days, args.test_days, args.step_days, args.min_train_trades) < 1:
        parser.error("Window lengths and minimum training trades must be positive")

    requested = [value.strip() for value in args.symbols.split(",") if value.strip()]
    client = DerivPublicClient(timeout=25)
    available = {client.symbol_code(item): item for item in client.synthetic_symbols()}
    unknown = [symbol for symbol in requested if symbol not in available]
    if unknown:
        parser.error(f"Symbols are not currently classified as active Deriv synthetics: {', '.join(unknown)}")

    print("MERCURYEDGE DERIV WALK-FORWARD — RESEARCH ONLY / NOT LIVE SIGNALS")
    print(
        f"Hourly candles: {args.count} | Outcome horizon: {args.horizon}h | "
        f"Train/test/step: {args.train_days}/{args.test_days}/{args.step_days} days"
    )
    print("Training outcomes are purged before each test boundary; overlapping same-symbol setups are suppressed.")
    print("No Telegram delivery, order placement, or production pipeline integration.")
    print("-" * 78)

    trade_frames = []
    for symbol in requested:
        raw = client.candles(symbol, count=args.count, granularity=args.granularity)
        frame = raw.rename(columns={
            "open": "Open", "high": "High", "low": "Low", "close": "Close"
        })
        frame["Volume"] = 0.0
        frame = frame[["Open", "High", "Low", "Close", "Volume"]].dropna()
        trades = build_trade_rows(frame, symbol, horizon=args.horizon)
        print(
            f"{symbol}: candles={len(frame)} matured_setups={len(trades)} "
            f"first={trades['ts'].min() if not trades.empty else 'n/a'} "
            f"last={trades['ts'].max() if not trades.empty else 'n/a'}"
        )
        if not trades.empty:
            trade_frames.append(trades)

    output = Path(os.getenv("RESEARCH_OUTPUT", "research_data/deriv-walk-forward"))
    output.mkdir(parents=True, exist_ok=True)
    if not trade_frames:
        report = {
            "status": "insufficient_data",
            "reason": "No matured Deriv strategy setups were generated.",
            "provider": "Deriv public market-data WebSocket",
            "symbols": requested,
            "strategy_rules_changed": False,
            "live_signal_filter_enabled": False,
        }
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0

    all_trades = pd.concat(trade_frames, ignore_index=True)
    all_trades.to_csv(output / "matured-trades.csv", index=False)
    folds, summary, report = walk_forward(
        all_trades,
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        horizon_hours=args.horizon,
        min_train_trades=args.min_train_trades,
        selection_cost_r=0.05,
        min_train_edge_r=0.02,
        costs_r=DEFAULT_COSTS_R,
    )
    report.update({
        "provider": "Deriv public market-data WebSocket",
        "symbols": requested,
        "granularity_seconds": args.granularity,
        "requested_candles_per_symbol": args.count,
        "strategy_rules_changed": False,
        "live_signal_filter_enabled": False,
        "execution_feed_verified": False,
        "warning": (
            "Research-only historical replay. R multiples use OHLC assumptions, not broker fills. "
            "Cost scenarios are illustrative, not verified Deriv contract costs. Positive results "
            "would still require contract-specific execution validation and paper trading."
        ),
    })
    folds.to_csv(output / "fold-results.csv", index=False)
    summary.to_csv(output / "oos-summary.csv", index=False)
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("\nOut-of-sample summary by baseline vs training-selected groups:")
    print(summary.to_string(index=False) if not summary.empty else "No eligible test windows.")
    if report["status"] != "completed":
        print("WARNING: insufficient chronological history for the configured windows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
