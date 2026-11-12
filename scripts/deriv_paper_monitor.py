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


def _overlap_flags(group: pd.DataFrame) -> pd.Series:
    """Mark the first trade in each non-overlapping strategy/symbol interval.

    A later signal whose 24-hour outcome interval intersects an earlier one is
    retained in the ledger but is not counted as independent evidence.
    """
    ordered = group.copy()
    ordered["_entry"] = pd.to_datetime(ordered["entry_time"], utc=True, errors="coerce")
    closed_at = pd.to_datetime(ordered["closed_time"], utc=True, errors="coerce")
    ordered["_end"] = closed_at.fillna(
        ordered["_entry"] + pd.Timedelta(hours=HORIZON_HOURS)
    )
    ordered = ordered.sort_values(["_entry", "trade_id"], kind="stable")
    flags = pd.Series(False, index=ordered.index, dtype=bool)
    cluster_end = None
    for idx, row in ordered.iterrows():
        entry = row["_entry"]
        finish = row["_end"]
        if pd.isna(entry) or pd.isna(finish):
            # Missing interval metadata cannot establish independence.
            continue
        if cluster_end is None or entry >= cluster_end:
            flags.loc[idx] = True
            cluster_end = finish
        elif finish > cluster_end:
            cluster_end = finish
    return flags.reindex(group.index, fill_value=False)


def build_report(ledger: pd.DataFrame, latest_candle: str) -> dict:
    data = ledger.copy()
    if data.empty:
        data = pd.DataFrame(columns=LEDGER_COLUMNS)
    for col in LEDGER_COLUMNS:
        if col not in data.columns:
            data[col] = ""
    data["_independent_evidence"] = False
    group_results = []
    overlap_groups = []

    # Group from the full ledger, not just closed rows, so open-only strategies
    # remain visible. Performance metrics below always use settled rows only.
    for (strategy, symbol), group in data.groupby(["strategy", "symbol"], dropna=False, sort=True):
        independent = _overlap_flags(group)
        data.loc[group.index, "_independent_evidence"] = independent
        closed = group[group.status == "CLOSED"].copy()
        independent_closed = closed.loc[independent.reindex(closed.index, fill_value=False)]
        row = {
            "strategy": strategy, "symbol": symbol,
            "open_trades": int((group.status == "OPEN").sum()),
            "closed_trades": int(len(closed)),
            "overlapping_signals": int((~independent).sum()),
            "independent_signals": int(independent.sum()),
        }
        for label, column in [
            ("1x_min_spread", "net_R_1x_min_spread"),
            ("1_5x_min_spread", "net_R_1_5x_min_spread"),
            ("2x_min_spread", "net_R_2x_min_spread"),
        ]:
            row[label] = _metrics(pd.to_numeric(closed[column], errors="coerce"))
            row[f"{label}_independent_only"] = _metrics(
                pd.to_numeric(independent_closed[column], errors="coerce")
            )
        group_results.append(row)
        overlap_groups.append({
            "strategy": strategy, "symbol": symbol,
            "signals": int(len(group)),
            "independent_signals": int(independent.sum()),
            "overlapping_signals": int((~independent).sum()),
            "independent_closed_signals": int(len(independent_closed)),
        })

    closed_all = data[data.status == "CLOSED"]
    independent_closed_all = data[
        (data.status == "CLOSED") & data["_independent_evidence"]
    ]
    overall = {}
    for label, column in [
        ("1x_min_spread", "net_R_1x_min_spread"),
        ("1_5x_min_spread", "net_R_1_5x_min_spread"),
        ("2x_min_spread", "net_R_2x_min_spread"),
    ]:
        overall[label] = _metrics(pd.to_numeric(closed_all[column], errors="coerce"))
        overall[f"{label}_independent_only"] = _metrics(
            pd.to_numeric(independent_closed_all[column], errors="coerce")
        )

    return {
        "status": "shadow_monitoring",
        "latest_completed_candle_utc": latest_candle,
        "holdout_start_utc": HOLDOUT_START.isoformat(),
        "signals_recorded": int(len(data)),
        "open_signals": int((data.status == "OPEN").sum()),
        "closed_signals": int((data.status == "CLOSED").sum()),
        "overall_settled_results": overall,
        "independence_warning": (
            "Signals with overlapping 24-hour outcome intervals are retained, "
            "but are not counted as independent evidence in the independent_only metrics."
        ),
        "overlap_analysis": {
            "method": "chronological non-overlapping 24-hour intervals per strategy and symbol",
            "independent_closed_signals": int(len(independent_closed_all)),
            "overlapping_signals": int((~data["_independent_evidence"]).sum()),
            "groups": overlap_groups,
        },
        "strategy_symbol_results": group_results,
        "cost_warning": "Published minimum spreads are scenario floors, not verified account-specific live execution costs. OHLC next-candle-open entries are proxies, not guaranteed fills. Slippage, commissions and swap conversion remain unverified.",
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
