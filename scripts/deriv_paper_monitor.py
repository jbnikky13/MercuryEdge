"""Hourly, persistent shadow-paper monitor for Deriv synthetic indices.

Signals are research observations only. No broker account, orders, Telegram, or
production MercuryEdge feed is touched. The ledger is committed by GitHub Actions
so runs remain continuous without a local PC or Codespace.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from mercuryedge.deriv_data import DerivPublicClient
from scripts.deriv_strategy_lab_v2 import (
    DEFAULT_SYMBOLS, DERIV_CFD_SPECS, HOLDOUT_START, HORIZON_HOURS,
    STRATEGIES, _direction, _features, _metrics, _settle,
)

LEDGER_COLUMNS = [
    "trade_id", "strategy", "symbol", "signal_time", "entry_time",
    "direction", "regime", "vol_regime", "entry", "risk_points",
    "stop", "target", "status", "closed_time", "gross_R",
    "net_R_1x_min_spread", "net_R_1_5x_min_spread", "net_R_2x_min_spread",
]


def _trade_id(strategy: str, symbol: str, signal_time: pd.Timestamp) -> str:
    return f"{strategy}|{symbol}|{signal_time.isoformat()}"


def update_ledger(frames: dict[str, pd.DataFrame], ledger: pd.DataFrame) -> pd.DataFrame:
    """Add unseen post-cutoff signals, then mature open outcomes from later candles."""
    existing = ledger.copy()
    for col in LEDGER_COLUMNS:
        if col not in existing.columns:
            existing[col] = pd.NA
    existing = existing[LEDGER_COLUMNS]
    known = set(existing.trade_id.dropna().astype(str))
    additions: list[dict] = []

    completed_cutoff = pd.Timestamp.now(tz="UTC").floor("h")
    for symbol, raw in frames.items():
        raw = raw.sort_index()
        completed = raw[raw.index < completed_cutoff]
        x = _features(completed)
        if len(x) < 302:
            continue
        # Evaluate only completed bars; use the following candle's recorded open
        # as the next-bar entry proxy, even while that entry candle is forming.
        for i in range(250, len(x)):
            signal_time = pd.Timestamp(x.index[i])
            if signal_time <= HOLDOUT_START:
                continue
            for strategy in STRATEGIES:
                direction = _direction(strategy, x.iloc[i], x.iloc[i - 1])
                if not direction:
                    continue
                trade_id = _trade_id(strategy, symbol, signal_time)
                if trade_id in known:
                    continue
                row = x.iloc[i]
                stop_mult = 1.0 + 0.5 * float(row.ATR_RANK)
                risk = float(row.ATR) * stop_mult
                if not pd.notna(risk) or risk <= 0:
                    continue
                entry_time = pd.Timestamp(x.index[i]) + pd.Timedelta(hours=1)
                if entry_time not in raw.index:
                    continue
                entry = float(raw.loc[entry_time, "Open"])
                side = 1.0 if direction == "BUY" else -1.0
                additions.append({
                    "trade_id": trade_id, "strategy": strategy, "symbol": symbol,
                    "signal_time": signal_time.isoformat(), "entry_time": entry_time.isoformat(),
                    "direction": direction, "regime": row.REGIME, "vol_regime": row.VOL_REGIME,
                    "entry": entry, "risk_points": risk,
                    "stop": entry - side * risk, "target": entry + side * risk * 1.6,
                    "status": "OPEN", "closed_time": "", "gross_R": "",
                    "net_R_1x_min_spread": "", "net_R_1_5x_min_spread": "",
                    "net_R_2x_min_spread": "",
                })
                known.add(trade_id)

    if additions:
        existing = pd.concat([existing, pd.DataFrame(additions)], ignore_index=True)

    # Resolve open rows only when the full 24-candle outcome window is present.
    for symbol, raw in frames.items():
        x = raw.sort_index()
        x = x[x.index < completed_cutoff]
        positions = {pd.Timestamp(ts).isoformat(): i for i, ts in enumerate(x.index)}
        mask = (existing.symbol == symbol) & (existing.status == "OPEN")
        for idx in existing.index[mask]:
            entry_time = pd.Timestamp(existing.at[idx, "entry_time"])
            pos = positions.get(entry_time.isoformat())
            if pos is None or pos + HORIZON_HOURS > len(x):
                continue
            future = x.iloc[pos:pos + HORIZON_HOURS]
            gross = _settle(str(existing.at[idx, "direction"]),
                            float(existing.at[idx, "entry"]),
                            float(existing.at[idx, "risk_points"]), future)
            spec = DERIV_CFD_SPECS.get(symbol)
            if not spec:
                continue
            risk = float(existing.at[idx, "risk_points"])
            spread_r = float(spec["min_spread"]) / risk
            existing.at[idx, "status"] = "CLOSED"
            existing.at[idx, "closed_time"] = pd.Timestamp(future.index[-1]).isoformat()
            existing.at[idx, "gross_R"] = gross
            existing.at[idx, "net_R_1x_min_spread"] = gross - spread_r
            existing.at[idx, "net_R_1_5x_min_spread"] = gross - spread_r * 1.5
            existing.at[idx, "net_R_2x_min_spread"] = gross - spread_r * 2.0

    return existing[LEDGER_COLUMNS].sort_values(
        ["signal_time", "symbol", "strategy"]
    ).reset_index(drop=True)


def build_report(ledger: pd.DataFrame, latest_candle: str) -> dict:
    closed = ledger[ledger.status == "CLOSED"].copy() if not ledger.empty else ledger.copy()
    strategies = []
    for (strategy, symbol), group in closed.groupby(["strategy", "symbol"]) if not closed.empty else []:
        row = {"strategy": strategy, "symbol": symbol,
               "open_trades": int(((ledger.strategy == strategy) & (ledger.symbol == symbol) &
                                   (ledger.status == "OPEN")).sum())}
        for label, column in [
            ("1x_min_spread", "net_R_1x_min_spread"),
            ("1_5x_min_spread", "net_R_1_5x_min_spread"),
            ("2x_min_spread", "net_R_2x_min_spread"),
        ]:
            row[label] = _metrics(pd.to_numeric(group[column], errors="coerce"))
        strategies.append(row)
    return {
        "status": "shadow_monitoring",
        "latest_completed_candle_utc": latest_candle,
        "holdout_start_utc": HOLDOUT_START.isoformat(),
        "signals_recorded": int(len(ledger)),
        "open_signals": int((ledger.status == "OPEN").sum()) if not ledger.empty else 0,
        "closed_signals": int((ledger.status == "CLOSED").sum()) if not ledger.empty else 0,
        "strategy_symbol_results": strategies,
        "cost_warning": "Published minimum spreads are scenario floors, not verified account-specific live execution costs. Slippage, commissions and swap conversion remain unverified.",
        "paper_eligible": False,
        "production_rules_changed": False,
        "telegram_enabled": False,
        "orders_placed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only Deriv shadow-paper monitor")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--count", type=int, default=5000)
    parser.add_argument("--ledger", default="research_data/deriv-shadow-paper/ledger.csv")
    parser.add_argument("--output", default="research_data/deriv-shadow-paper")
    args = parser.parse_args()
    if not 400 <= args.count <= 5000:
        parser.error("count must be between 400 and 5000")
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    client = DerivPublicClient(timeout=25)
    active = {client.symbol_code(item): item for item in client.synthetic_symbols()}
    unknown = [s for s in symbols if s not in active]
    if unknown:
        parser.error(f"Not active Deriv synthetic symbols: {unknown}")

    ledger_path = Path(args.ledger)
    output = Path(args.output)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    ledger = pd.read_csv(ledger_path, keep_default_na=False) if ledger_path.exists() else pd.DataFrame(columns=LEDGER_COLUMNS)
    frames = {}
    latest = None
    for symbol in symbols:
        raw = client.candles(symbol, count=args.count, granularity=3600)
        raw = raw.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})
        completed = raw[raw.index < pd.Timestamp.now(tz="UTC").floor("h")]
        if completed.empty:
            continue
        frames[symbol] = raw
        latest = max(latest, completed.index.max()) if latest is not None else completed.index.max()
        print(f"{symbol}: completed_hourly_candles={len(completed)} latest={completed.index.max().isoformat()}")

    if not frames:
        raise RuntimeError("No completed hourly candles returned; ledger was not changed.")
    ledger = update_ledger(frames, ledger)
    ledger.to_csv(ledger_path, index=False)
    report = build_report(ledger, pd.Timestamp(latest).isoformat())
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output / "latest-ledger.csv").write_text(ledger.to_csv(index=False), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
