"""Point-in-time replay of MercuryEdge's scheduled live signal pipeline.

This is a research approximation, not broker-execution simulation. It replays
completed hourly candles at the configured WAT scan times, recomputes historical
and cross-market context from data available by each scan, applies the quality
gate and ADX/HTF/exposure/top-N selectors, then grades selected signals.

Historical headlines, contemporaneous 5-minute executable quotes, and archived
versions of adaptive calibration files are not available in the historical
artifact; those components are explicitly reported as omitted.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from mercuryedge.analysis import add_indicators, analyze
from mercuryedge.calendar import ET, WAT, trading_status
from mercuryedge.config import (
    MARKETS, MAX_CURRENCY_EXPOSURE, MAX_SETUPS, MIN_ADX,
    REQUIRE_HTF_TREND, SIGNAL_HORIZON_HOURS,
)
from mercuryedge.crossmarket import build_context as build_crossmarket_context
from mercuryedge.historical import build_context as build_historical_context
from mercuryedge.upgrades import select_setups
from scripts.research_historical import _settle_one
from signal_filters import filter_batch

ROOT = Path(os.getenv("RESEARCH_OUTPUT", "research_data"))
SLOT_TIMES = {
    "overnight": (1, 30),
    "morning": (6, 30),
    "afternoon": (16, 30),
    "evening": (20, 30),
}
COOLDOWN_HOURS = 12
MAX_RESEARCH_HORIZON_HOURS = 120  # up to five trading days of hourly bars


def _horizon_hours(label: str) -> int:
    return {
        "INTRADAY_0_24H": 24,
        "SWING_24_72H": 72,
        "POSITION_3_5D": MAX_RESEARCH_HORIZON_HOURS,
    }.get(str(label), 24)


def _read_market(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return frame.dropna(subset=["Open", "High", "Low", "Close"])


def _load_frames(root: Path):
    hourly, daily, enriched = {}, {}, {}
    for market in MARKETS:
        h = _read_market(root / "hourly" / f"{market.name}.csv")
        d = _read_market(root / "daily" / f"{market.name}.csv")
        if not h.empty:
            hourly[market.name] = h
            try:
                enriched[market.name] = add_indicators(h)
            except (ValueError, KeyError):
                continue
        if not d.empty:
            daily[market.name] = d
    return hourly, daily, enriched


def _scan_times(hourly: dict[str, pd.DataFrame]) -> list[tuple[pd.Timestamp, str]]:
    if not hourly:
        return []
    first = min(frame.index.min() for frame in hourly.values()).tz_convert(WAT).date()
    last = max(frame.index.max() for frame in hourly.values()).tz_convert(WAT).date()
    rows = []
    day = first
    while day <= last:
        for slot, (hour, minute) in SLOT_TIMES.items():
            local = datetime.combine(day, time(hour, minute), tzinfo=WAT)
            rows.append((pd.Timestamp(local.astimezone(ZoneInfo("UTC"))), slot))
        day += timedelta(days=1)
    return sorted(rows, key=lambda item: item[0])


def _latest_completed_prefix(frame: pd.DataFrame, scan_ts: pd.Timestamp):
    """Hourly indexes label candle starts; require candle end <= scan time."""
    if frame is None or frame.empty:
        return frame.iloc[0:0] if frame is not None else pd.DataFrame()
    cutoff = scan_ts - pd.Timedelta(hours=1)
    pos = frame.index.searchsorted(cutoff, side="right")
    return frame.iloc[:pos]


def _is_scan_allowed(scan_ts: pd.Timestamp, slot: str) -> tuple[bool, bool]:
    local = scan_ts.tz_convert(WAT)
    if slot in {"overnight", "morning"}:
        return local.weekday() < 5, False
    allowed, reason = trading_status(scan_ts.to_pydatetime())
    if allowed:
        return True, False
    if reason == "past 16:00 ET scan cutoff" and slot in {"afternoon", "evening"}:
        return True, True
    return False, False


def _signal_resolved_before_scan(signal: dict, hourly: dict, scan_ts: pd.Timestamp) -> bool:
    """True when stop or TP2 was touched on a fully completed bar since entry."""
    frame = hourly.get(signal["symbol"])
    if frame is None or frame.empty:
        return False
    start = pd.Timestamp(signal["scan_ts"]).ceil("h")
    cutoff = scan_ts - pd.Timedelta(hours=1)
    future = frame[(frame.index >= start) & (frame.index <= cutoff)]
    side = 1 if signal["direction"] == "BUY" else -1
    for _, candle in future.iterrows():
        stop_hit = candle["Low"] <= signal["sl"] if side == 1 else candle["High"] >= signal["sl"]
        tp2_hit = candle["High"] >= signal["tp2"] if side == 1 else candle["Low"] <= signal["tp2"]
        if stop_hit or tp2_hit:
            return True
    return False


def _settle_selected(signal: dict, hourly: dict) -> dict | None:
    frame = hourly.get(signal["symbol"])
    if frame is None or frame.empty:
        return None
    scan_ts = pd.Timestamp(signal["scan_ts"])
    future_start = scan_ts.ceil("h")
    future = frame[frame.index >= future_start].iloc[:MAX_RESEARCH_HORIZON_HOURS]
    if len(future) < SIGNAL_HORIZON_HOURS:
        return None
    risk = abs(float(signal["entry"]) - float(signal["sl"]))
    settlement_24h = _settle_one(
        pd.Series({
            "direction": signal["direction"],
            "entry": float(signal["entry"]),
            "risk": risk,
            "sl": float(signal["sl"]),
            "tp1": float(signal["tp1"]),
            "tp2": float(signal["tp2"]),
        }),
        future.iloc[:SIGNAL_HORIZON_HOURS],
    )
    settlement_120h = _settle_one(
        pd.Series({
            "direction": signal["direction"],
            "entry": float(signal["entry"]),
            "risk": risk,
            "sl": float(signal["sl"]),
            "tp1": float(signal["tp1"]),
            "tp2": float(signal["tp2"]),
        }),
        future,
    ) if len(future) >= MAX_RESEARCH_HORIZON_HOURS else None

    side = 1 if signal["direction"] == "BUY" else -1
    tp1_time = tp2_time = stop_time = None
    for candle_ts, candle in future.iterrows():
        elapsed_hours = max(1, int(np.ceil((candle_ts + pd.Timedelta(hours=1) - scan_ts).total_seconds() / 3600)))
        high, low = float(candle["High"]), float(candle["Low"])
        stop_hit = low <= signal["sl"] if side == 1 else high >= signal["sl"]
        tp1_hit = high >= signal["tp1"] if side == 1 else low <= signal["tp1"]
        tp2_hit = high >= signal["tp2"] if side == 1 else low <= signal["tp2"]
        # Conservative stop-first ordering for ambiguous hourly candles.
        if stop_hit:
            stop_time = elapsed_hours
            break
        if tp2_hit:
            tp1_time = tp1_time or elapsed_hours
            tp2_time = elapsed_hours
            break
        if tp1_hit and tp1_time is None:
            tp1_time = elapsed_hours
    actual_hours = tp1_time if tp1_time is not None else stop_time
    if actual_hours is None:
        actual_window = "NOT_REACHED_WITHIN_5D" if len(future) >= MAX_RESEARCH_HORIZON_HOURS else "INSUFFICIENT_FUTURE_DATA"
    elif actual_hours <= 24:
        actual_window = "0_24H"
    elif actual_hours <= 72:
        actual_window = "24_72H"
    else:
        actual_window = "72_120H"
    return {
        **settlement_24h,
        "outcome_24h": settlement_24h.get("outcome"),
        "tp1_full_R_24h": settlement_24h.get("tp1_full_R"),
        "tp2_full_R_24h": settlement_24h.get("tp2_full_R"),
        "outcome_120h": settlement_120h.get("outcome") if settlement_120h else None,
        "tp1_full_R_120h": settlement_120h.get("tp1_full_R") if settlement_120h else None,
        "tp2_full_R_120h": settlement_120h.get("tp2_full_R") if settlement_120h else None,
        "tp1_time_hours": tp1_time,
        "tp2_time_hours": tp2_time,
        "stop_time_hours": stop_time,
        "actual_holding_window": actual_window,
    }


def replay(root: Path = ROOT) -> tuple[pd.DataFrame, dict]:
    hourly, daily, enriched = _load_frames(root)
    if not hourly:
        raise FileNotFoundError(f"No hourly market CSVs found under {root / 'hourly'}")

    scan_rows = []
    last_sent: dict[str, pd.Timestamp] = {}
    active_signals: list[dict] = []
    context_cache = {}
    for scan_ts, slot in _scan_times(hourly):
        allowed, late_us_scan = _is_scan_allowed(scan_ts, slot)
        if not allowed:
            continue

        market_slices = {
            name: _latest_completed_prefix(frame, scan_ts)
            for name, frame in hourly.items()
        }
        candidates = []
        for market in MARKETS:
            raw = hourly.get(market.name)
            indicators = enriched.get(market.name)
            if raw is None or indicators is None:
                continue
            raw_prefix = market_slices[market.name]
            cutoff = scan_ts - pd.Timedelta(hours=1)
            enriched_prefix = indicators.loc[indicators.index <= cutoff]
            if len(enriched_prefix) < 220 or raw_prefix.empty:
                continue

            base = analyze(enriched_prefix)
            if not base:
                continue

            cache_key = (market.name, base["direction"], scan_ts.date().isoformat())
            if cache_key not in context_cache:
                hist = daily.get(market.name)
                context_cache[cache_key] = (
                    build_historical_context(
                        hist, direction=base["direction"], timestamp=scan_ts
                    )
                    if hist is not None and not hist.empty else None
                )
            context = context_cache[cache_key]
            result = analyze(enriched_prefix, context)
            if not result:
                continue

            cross = build_crossmarket_context(
                market.name, result["direction"], market_slices
            )
            result["crossmarket_score"] = cross.score
            result["crossmarket_agreement"] = cross.agreement
            # Do not apply current adaptive-calibration files retroactively:
            # historical snapshots are unavailable, so that would leak future state.
            result["score"] = int(np.clip(result["score"] + cross.score, 0, 100))

            candidates.append({
                "symbol": market.name,
                "direction": result["direction"],
                "score": result["score"],
                "_market": market,
                "_setup": result,
                "_frame": raw_prefix,
            })

        batch_symbols = next(
            (symbols for name, _time, symbols in __import__("scheduler").BATCHES
             if name.lower() == slot),
            set(),
        )
        candidates = [
            item for item in candidates
            if item["symbol"] in batch_symbols
            and (not late_us_scan or item["_market"].category != "index")
        ]

        filter_candidates, candidate_by_key = [], {}
        for item in candidates:
            setup = item["_setup"]
            # Match the live quality gate to the 24h signal horizon.
            horizon = setup.get("historical_holding_period", "NO_HORIZON_EDGE")
            horizon_field = {
                "INTRADAY_0_24H": "historical_win_rate_1d",
                "SWING_24_72H": "historical_win_rate_3d",
                "POSITION_3_5D": "historical_win_rate_5d",
            }.get(horizon)
            rate = setup.get(horizon_field) if horizon_field else None
            sig = {
                "symbol": item["symbol"],
                "direction": item["direction"],
                "entry": setup.get("entry"),
                "score": setup.get("score"),
                "hit_rate": float(rate) * 100 if rate is not None else None,
                "analogues": setup.get("historical_samples"),
                "regime": setup.get("historical_regime"),
                "confirmation": setup.get("crossmarket_score", 0),
                "tp1": setup.get("tp1"),
                "tp2": setup.get("tp2"),
                "sl": setup.get("sl"),
            }
            filter_candidates.append(sig)
            candidate_by_key[(sig["symbol"], sig["direction"])] = item

        blocked = {
            symbol: 1 for symbol, sent_ts in last_sent.items()
            if pd.Timedelta(0) <= scan_ts - sent_ts < pd.Timedelta(hours=COOLDOWN_HOURS)
        }
        kept, _dropped = filter_batch(
            filter_candidates, price_lookup=None, already_sent_today=blocked
        )
        eligible = [candidate_by_key[(sig["symbol"], sig["direction"])] for sig in kept]

        active_signals = [
            signal for signal in active_signals
            if scan_ts - pd.Timestamp(signal["scan_ts"]) < pd.Timedelta(hours=_horizon_hours(signal.get("holding_period", "INTRADAY_0_24H")))
            and not _signal_resolved_before_scan(signal, hourly, scan_ts)
        ]
        selected, _skipped = select_setups(
            eligible,
            market_slices,
            max_setups=MAX_SETUPS,
            existing=active_signals,
            min_adx=MIN_ADX,
            require_htf=REQUIRE_HTF_TREND,
            max_per_ccy=MAX_CURRENCY_EXPOSURE,
        )

        for item in selected:
            setup = item["_setup"]
            signal = {
                "scan_ts": scan_ts.isoformat(),
                "slot": slot,
                "symbol": item["symbol"],
                "direction": item["direction"],
                "score": int(item["score"]),
                "setup": setup.get("setup"),
                "entry": float(setup["entry"]),
                "sl": float(setup["sl"]),
                "tp1": float(setup["tp1"]),
                "tp2": float(setup["tp2"]),
                "historical_samples": int(setup.get("historical_samples") or 0),
                "historical_win_rate_1d_pct": (
                    float(setup["historical_win_rate_1d"]) * 100
                    if setup.get("historical_win_rate_1d") is not None else None
                ),
                "historical_win_rate_3d_pct": (
                    float(setup["historical_win_rate_3d"]) * 100
                    if setup.get("historical_win_rate_3d") is not None else None
                ),
                "historical_win_rate_5d_pct": (
                    float(setup["historical_win_rate_5d"]) * 100
                    if setup.get("historical_win_rate_5d") is not None else None
                ),
                "holding_period": setup.get("historical_holding_period", "NO_HORIZON_EDGE"),
                "crossmarket_score": int(setup.get("crossmarket_score") or 0),
                "adx_min": MIN_ADX,
                "htf_required": REQUIRE_HTF_TREND,
            }
            settlement = _settle_selected(signal, hourly)
            if settlement is None:
                continue
            scan_rows.append({**signal, **settlement})
            active_signals.append(signal)
            last_sent[item["symbol"]] = scan_ts

    trades = pd.DataFrame(scan_rows)
    if not trades.empty:
        trades["scan_ts"] = pd.to_datetime(trades["scan_ts"], utc=True)
        trades = trades.sort_values(["scan_ts", "symbol"]).reset_index(drop=True)
    else:
        trades = pd.DataFrame(columns=[
            "scan_ts", "slot", "symbol", "direction", "score", "setup",
            "entry", "sl", "tp1", "tp2", "historical_samples",
            "historical_win_rate_1d_pct", "historical_win_rate_3d_pct",
            "historical_win_rate_5d_pct", "holding_period", "crossmarket_score", "adx_min",
            "htf_required", "outcome", "tp1_hit", "tp1_full_R",
            "tp2_full_R", "half_be_R", "half_sl_R",
        ])
    trades.to_csv(root / "live-pipeline-replay.csv", index=False)

    report = {
        "replayed_selected_signals": int(len(trades)),
        "scan_slots_wat": {slot: f"{hour:02d}:{minute:02d}" for slot, (hour, minute) in SLOT_TIMES.items()},
        "entry_reference": "last completed hourly close available at scan time; no contemporaneous 5m execution quote",
        "outcome_horizon_hours": SIGNAL_HORIZON_HOURS,
        "extended_research_horizon_hours": MAX_RESEARCH_HORIZON_HOURS,
        "duration_policy": "Select the shortest qualifying historical horizon (1d, 3d, then 5d); report 24h and up-to-120h outcomes separately and label target/stop timing.",
        "included": [
            "core EMA/RSI/MACD/breakout rules",
            "matured historical analogue context",
            "rolling cross-market context",
            "score plus shortest qualifying 1-day, 3-day or 5-day directional analogue hit-rate gate",
            "holding-window classification and separate 24-hour versus up-to-120-hour outcome grading",
            "ADX and completed-4h trend gate",
            "12-hour same-symbol cooldown",
            "duration-aware active-signal exposure (24h, 72h or 120h) and currency exposure cap",
            "scheduled market universe and four-setup cap",
        ],
        "omitted_or_approximated": [
            "historical NFP/news headlines (no archived feed)",
            "historical 5-minute executable quotes and live feed-deviation check",
            "adaptive calibration modifiers (no point-in-time calibration snapshots)",
            "broker spread, slippage, financing and instrument contract mapping",
            "signal status transitions are approximated as active until SL/TP2 or the analogue-selected 24h/72h/120h window",
        ],
        "data_provider": "Yahoo Finance hourly/daily candles; research proxy only",
        "warning": "Research-only replay. Do not enable live trading based on this artifact alone.",
    }
    (root / "live-pipeline-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return trades, report


def main():
    trades, report = replay()
    print(json.dumps(report, indent=2))
    if not trades.empty:
        print(trades.groupby("slot").size().to_string())


if __name__ == "__main__":
    main()
