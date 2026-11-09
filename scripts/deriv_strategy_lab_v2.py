"""Deriv Strategy Lab v2: regime-aware, volatility-scaled, forward-only research.

This module is isolated from production signals and execution. It deliberately
uses a frozen historical cutoff so all post-cutoff candles form a prospective,
untouched holdout. A short holdout is reported as immature, never backfilled.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from mercuryedge.deriv_data import DerivPublicClient

# Frozen at the end of the v1 dataset (candidate-trades.csv ended 2026-11-08 07:00Z).
# Never move this forward to make a weak result look better.
HOLDOUT_START = pd.Timestamp("2026-11-08T07:00:00Z")
DEFAULT_SYMBOLS = ("R_10", "R_25", "R_50", "R_75", "R_100")
STRATEGIES = ("regime_pullback", "regime_breakout")
HORIZON_HOURS = 24
TEST_BLOCK_DAYS = 30
MIN_COMPLETE_BLOCKS = 4
MIN_TRADES = 100
MIN_POSITIVE_BLOCK_SHARE = 0.75
MIN_PROFIT_FACTOR = 1.20
MAX_DRAWDOWN_R = 12.0

# Snapshot of Deriv's published Derived Indices CFD specifications, accessed
# 2026-11-09. min_spread is a price-point floor, not a guaranteed live spread.
# Recheck on Deriv before paper testing; product/account offerings can differ.
# Source: https://deriv.com/ae/markets/derived-indices?f4c9ef94_page=1
# and https://deriv.com/ae/markets/derived-indices?f4c9ef94_page=2
DERIV_CFD_SPECS = {
    "R_10":  {"display_name": "Volatility 10 Index",  "contract_size": 1, "base_currency": "USD", "min_size": 0.5, "volume_limit": 1280, "min_spread": 0.188, "target_spread_pct": 0.00, "max_leverage": 1000, "margin_pct": 0.10, "swap_long_pts": -1.0, "swap_short_pts": -1.0},
    "R_25":  {"display_name": "Volatility 25 Index",  "contract_size": 1, "base_currency": "USD", "min_size": 0.5, "volume_limit": 1000, "min_spread": 0.331, "target_spread_pct": 0.01, "max_leverage": 1000, "margin_pct": 0.10, "swap_long_pts": -2.5, "swap_short_pts": -2.5},
    "R_50":  {"display_name": "Volatility 50 Index",  "contract_size": 1, "base_currency": "USD", "min_size": 4.0, "volume_limit": 12000, "min_spread": 0.023, "target_spread_pct": 0.02, "max_leverage": 500, "margin_pct": 0.20, "swap_long_pts": -5.0, "swap_short_pts": -5.0},
    "R_75":  {"display_name": "Volatility 75 Index",  "contract_size": 1, "base_currency": "USD", "min_size": 0.01, "volume_limit": 50, "min_spread": 12.09, "target_spread_pct": 0.04, "max_leverage": 500, "margin_pct": 0.20, "swap_long_pts": -7.5, "swap_short_pts": -7.5},
    "R_100": {"display_name": "Volatility 100 Index", "contract_size": 1, "base_currency": "USD", "min_size": 1.0, "volume_limit": 1000, "min_spread": 0.29, "target_spread_pct": 0.05, "max_leverage": 500, "margin_pct": 0.20, "swap_long_pts": -10.0, "swap_short_pts": -10.0},
}
COST_MULTIPLIERS = (1.0, 1.5, 2.0)


def _features(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(frame.columns):
        raise ValueError(f"OHLC frame missing columns: {sorted(required - set(frame.columns))}")
    x = frame.copy().sort_index()
    for c in ("Open", "High", "Low", "Close"):
        x[c] = pd.to_numeric(x[c], errors="coerce")
    prev_close = x.Close.shift(1)
    tr = pd.concat([(x.High - x.Low), (x.High - prev_close).abs(),
                    (x.Low - prev_close).abs()], axis=1).max(axis=1)
    x["ATR"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    up = x.High.diff()
    down = -x.Low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / x.ATR
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / x.ATR
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    x["ADX"] = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    x["EMA20"] = x.Close.ewm(span=20, adjust=False).mean()
    x["EMA50"] = x.Close.ewm(span=50, adjust=False).mean()
    x["EMA200"] = x.Close.ewm(span=200, adjust=False).mean()
    x["EMA50_SLOPE"] = (x.EMA50 - x.EMA50.shift(5)) / (5 * x.ATR)
    fast = x.Close.ewm(span=12, adjust=False).mean()
    slow = x.Close.ewm(span=26, adjust=False).mean()
    x["MACD_HIST"] = (fast - slow) - (fast - slow).ewm(span=9, adjust=False).mean()
    x["RSI"] = 100 - 100 / (1 + (x.Close.diff().clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
                                  / (-x.Close.diff().clip(upper=0)).ewm(alpha=1/14, adjust=False).mean().replace(0, np.nan)))
    atr_pct = x.ATR / x.Close.replace(0, np.nan)
    x["ATR_PCT"] = atr_pct
    x["ATR_RANK"] = atr_pct.rolling(200, min_periods=80).apply(
        lambda a: float((a[-1] >= a[:-1]).mean()) if len(a) > 1 else np.nan, raw=True
    )
    x["DONCHIAN_HIGH"] = x.High.shift(1).rolling(20, min_periods=20).max()
    x["DONCHIAN_LOW"] = x.Low.shift(1).rolling(20, min_periods=20).min()
    x["REGIME"] = np.select(
        [(x.ADX >= 22) & (x.EMA50_SLOPE.abs() >= 0.04),
         (x.ADX <= 16) & (x.EMA50_SLOPE.abs() <= 0.025)],
        ["TREND", "RANGE"], default="TRANSITION"
    )
    x["VOL_REGIME"] = np.select(
        [x.ATR_RANK <= 0.25, x.ATR_RANK <= 0.75, x.ATR_RANK <= 0.95],
        ["QUIET", "NORMAL", "ELEVATED"], default="EXTREME"
    )
    return x


def _direction(strategy: str, row: pd.Series, prev: pd.Series) -> str | None:
    if row.REGIME != "TREND" or row.VOL_REGIME in ("QUIET", "EXTREME"):
        return None
    up = row.EMA20 > row.EMA50 > row.EMA200 and row.EMA50_SLOPE >= 0.04
    down = row.EMA20 < row.EMA50 < row.EMA200 and row.EMA50_SLOPE <= -0.04
    bullish = row.Close > row.Open and row.Close > prev.Close
    bearish = row.Close < row.Open and row.Close < prev.Close
    if strategy == "regime_pullback":
        buy = (up and row.Low <= row.EMA20 + 0.10 * row.ATR and row.Close > row.EMA20
               and bullish and 52 <= row.RSI <= 68 and row.MACD_HIST > 0 and row.ADX >= 22)
        sell = (down and row.High >= row.EMA20 - 0.10 * row.ATR and row.Close < row.EMA20
                and bearish and 32 <= row.RSI <= 48 and row.MACD_HIST < 0 and row.ADX >= 22)
    elif strategy == "regime_breakout":
        buy = (up and row.Close > row.DONCHIAN_HIGH and bullish and row.Close - row.Open >= 0.5 * row.ATR
               and row.RSI >= 55 and row.MACD_HIST > 0 and row.ADX >= 25)
        sell = (down and row.Close < row.DONCHIAN_LOW and bearish and row.Open - row.Close >= 0.5 * row.ATR
                and row.RSI <= 45 and row.MACD_HIST < 0 and row.ADX >= 25)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")
    return "BUY" if buy else "SELL" if sell else None


def _settle(direction: str, entry: float, risk: float, future: pd.DataFrame) -> float:
    side = 1.0 if direction == "BUY" else -1.0
    stop, target = entry - side * risk, entry + side * risk * 1.6
    for _, bar in future.iterrows():
        # Model gap-through-stop at the worse opening price; do not cap every stop
        # loss at exactly -1R when the next candle opens beyond the stop.
        if direction == "BUY" and bar.Open <= stop:
            return float((bar.Open - entry) / risk)
        if direction == "SELL" and bar.Open >= stop:
            return float((entry - bar.Open) / risk)
        stop_hit = bar.Low <= stop if direction == "BUY" else bar.High >= stop
        target_hit = bar.High >= target if direction == "BUY" else bar.Low <= target
        if stop_hit:  # conservative tie-break when intrabar order is unknowable
            return -1.0
        if target_hit:
            return 1.6
    last = float(future.Close.iloc[-1])
    return float(np.clip((last - entry) * side / risk, -1.0, 1.6))


def build_trades(frame: pd.DataFrame, symbol: str, cutoff: pd.Timestamp = HOLDOUT_START,
                 horizon: int = HORIZON_HOURS) -> pd.DataFrame:
    """Create outcomes only for signals strictly after frozen cutoff."""
    x = _features(frame)
    if len(x) <= 300 + horizon:
        return pd.DataFrame()
    rows = []
    for i in range(250, len(x) - horizon):
        ts = x.index[i]
        if ts <= cutoff:
            continue
        row, prev = x.iloc[i], x.iloc[i - 1]
        if row.VOL_REGIME == "EXTREME" or not np.isfinite(row.ATR_RANK):
            continue
        for strategy in STRATEGIES:
            direction = _direction(strategy, row, prev)
            if not direction:
                continue
            # Volatility-adjusted stop: widen modestly as trailing ATR percentile rises.
            stop_mult = 1.0 + 0.5 * float(row.ATR_RANK)
            risk = float(row.ATR) * stop_mult
            if not np.isfinite(risk) or risk <= 0:
                continue
            future = x.iloc[i + 1:i + 1 + horizon]
            if len(future) != horizon:
                continue
            # Signal is confirmed at this candle's close; earliest defensible
            # OHLC fill proxy is the next candle's open, not the signal close.
            entry = float(future.Open.iloc[0])
            rows.append({
                "strategy": strategy, "symbol": symbol, "ts": ts.isoformat(),
                "direction": direction, "regime": row.REGIME, "vol_regime": row.VOL_REGIME,
                "adx": float(row.ADX), "atr_rank": float(row.ATR_RANK),
                "stop_atr": stop_mult, "signal_close": float(row.Close),
                "entry": entry, "risk_points": risk,
                "gross_R": _settle(direction, entry, risk, future),
            })
    return pd.DataFrame(rows)


def _metrics(values: pd.Series) -> dict:
    v = pd.to_numeric(values, errors="coerce").dropna()
    if v.empty:
        return {"trades": 0, "mean_net_R": None, "profit_factor": None,
                "max_drawdown_R": None, "win_rate_pct": None}
    gains, losses = float(v[v > 0].sum()), float(-v[v < 0].sum())
    equity = v.cumsum()
    dd = equity - equity.cummax().clip(lower=0)
    return {"trades": int(len(v)), "mean_net_R": round(float(v.mean()), 5),
            "profit_factor": round(gains / losses, 4) if losses else (None if not gains else float("inf")),
            "max_drawdown_R": round(float(dd.min()), 4),
            "win_rate_pct": round(float((v > 0).mean() * 100), 2)}


def evaluate_holdout(trades: pd.DataFrame, specs: dict[str, dict],
                     max_timestamp: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Evaluate only completed 30-day blocks after cutoff; no tuning/selection."""
    holdout_days = max(0.0, (max_timestamp - HOLDOUT_START).total_seconds() / 86400)
    complete_blocks = int(holdout_days // TEST_BLOCK_DAYS)
    block_rows, summary_rows = [], []
    data = trades.copy()
    if not data.empty:
        data["ts"] = pd.to_datetime(data.ts, utc=True)
        data = data.sort_values(["ts", "symbol", "strategy"])
        data["block"] = ((data.ts - HOLDOUT_START).dt.total_seconds() // (TEST_BLOCK_DAYS * 86400)).astype(int)
        data = data[data.block < complete_blocks]
    for (strategy, symbol), group in data.groupby(["strategy", "symbol"]) if not data.empty else []:
        spec = specs.get(symbol)
        if not spec or not spec.get("min_spread"):
            continue
        for multiplier in COST_MULTIPLIERS:
            costs = group.risk_points.astype(float).rdiv(float(spec["min_spread"])) * multiplier
            group_net = group.gross_R.astype(float) - costs
            block_means = []
            # Count every completed calendar block, including blocks with zero trades.
            # Otherwise sparse strategies could look consistent by skipping quiet months.
            for block in range(complete_blocks):
                mask = group.block == block
                vals = group_net.loc[mask]
                stats = _metrics(vals)
                block_means.append(stats["mean_net_R"])
                block_rows.append({"strategy": strategy, "symbol": symbol,
                                   "cost_spread_multiple": multiplier, "block": block, **stats})
            stats = _metrics(group_net)
            positive_share = sum(x is not None and x > 0 for x in block_means) / complete_blocks if complete_blocks else 0.0
            summary_rows.append({"strategy": strategy, "symbol": symbol, "cost_spread_multiple": multiplier,
                                 **stats, "complete_blocks": complete_blocks,
                                 "positive_block_share": round(float(positive_share), 3)})
    blocks = pd.DataFrame(block_rows)
    summary = pd.DataFrame(summary_rows)
    report = {
        "status": "holdout_not_matured" if complete_blocks < MIN_COMPLETE_BLOCKS else "evaluated",
        "frozen_holdout_start_utc": HOLDOUT_START.isoformat(),
        "latest_candle_utc": max_timestamp.isoformat(),
        "holdout_days_available": round(holdout_days, 2),
        "complete_30_day_blocks": complete_blocks,
        "minimum_complete_blocks_required": MIN_COMPLETE_BLOCKS,
        "candidate_trades_in_holdout": int(len(trades)),
        "paper_gate_criteria": {
            "minimum_trades": MIN_TRADES, "minimum_positive_block_share": MIN_POSITIVE_BLOCK_SHARE,
            "minimum_profit_factor_at_2x_min_spread": MIN_PROFIT_FACTOR,
            "maximum_drawdown_R": MAX_DRAWDOWN_R,
            "all_costs_and_account_contract_details_verified": False,
        },
        "paper_eligible": False,
        "reason": "Fresh holdout is not yet mature; execution costs beyond published minimum spread are not verified.",
        "production_rules_changed": False, "telegram_enabled": False, "orders_placed": False,
    }
    if not summary.empty and complete_blocks >= MIN_COMPLETE_BLOCKS:
        strict = summary[summary.cost_spread_multiple == 2.0]
        passed = strict[
            (strict.trades >= MIN_TRADES) & (strict.mean_net_R > 0) &
            (strict.profit_factor >= MIN_PROFIT_FACTOR) &
            (strict.max_drawdown_R >= -MAX_DRAWDOWN_R) &
            (strict.positive_block_share >= MIN_POSITIVE_BLOCK_SHARE) &
            (strict.complete_blocks >= MIN_COMPLETE_BLOCKS)
        ]
        report["statistical_candidates_passing"] = passed[["strategy", "symbol"]].to_dict("records")
        report["paper_eligible"] = False  # must remain false until account-specific execution costs are verified
        report["reason"] = "Statistical screen may pass, but paper eligibility remains blocked pending verified live contract costs."
    return blocks, summary, report


def main() -> int:
    p = argparse.ArgumentParser(description="Prospective, research-only Deriv regime strategy lab v2")
    p.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    p.add_argument("--count", type=int, default=5000)
    args = p.parse_args()
    if not 400 <= args.count <= 5000:
        p.error("count must be between 400 and 5000")
    requested = [s.strip() for s in args.symbols.split(",") if s.strip()]
    client = DerivPublicClient(timeout=25)
    active = {client.symbol_code(item): item for item in client.synthetic_symbols()}
    unknown = [s for s in requested if s not in active]
    if unknown:
        p.error(f"Not active Deriv synthetic symbols: {unknown}")
    output = Path(os.getenv("RESEARCH_OUTPUT", "research_data/deriv-strategy-lab-v2"))
    output.mkdir(parents=True, exist_ok=True)
    all_trades, metadata = [], {}
    max_ts = None
    for symbol in requested:
        item = active[symbol]
        raw = client.candles(symbol, count=args.count, granularity=3600)
        frame = raw.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})
        trades = build_trades(frame, symbol)
        all_trades.append(trades)
        max_ts = frame.index.max() if max_ts is None else max(max_ts, frame.index.max())
        spec = DERIV_CFD_SPECS.get(symbol, {}).copy()
        spec["api_pip_size"] = item.get("pip_size")
        spec["api_symbol_name"] = client.symbol_name(item)
        spec["api_market"] = item.get("market")
        spec["published_spec_source"] = "https://deriv.com/ae/markets/derived-indices"
        spec["published_spec_as_of"] = "2026-11-09"
        spec["published_min_spread_is_not_live_quote"] = True
        metadata[symbol] = spec
        print(f"{symbol}: candles={len(frame)} prospective_trades={len(trades)}")
    trades = pd.concat([x for x in all_trades if not x.empty], ignore_index=True) if any(not x.empty for x in all_trades) else pd.DataFrame()
    blocks, summary, report = evaluate_holdout(trades, metadata, pd.Timestamp(max_ts))
    trades.to_csv(output / "prospective-holdout-trades.csv", index=False)
    blocks.to_csv(output / "holdout-block-results.csv", index=False)
    summary.to_csv(output / "holdout-summary.csv", index=False)
    (output / "contract-specifications.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not summary.empty:
        print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
