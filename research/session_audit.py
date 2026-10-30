from __future__ import annotations

import csv
import json
import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from market_data import SYMBOLS, get_candles
from mercuryedge.config import MARKETS

LOG = logging.getLogger("mercuryedge.session_audit")
WAT = ZoneInfo("Africa/Lagos")
OUT = Path("research_data/session_audit")
JOURNAL = Path("data/journal.jsonl")


def session_bounds(session_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(session_date, time.min, tzinfo=WAT).astimezone(timezone.utc)
    end = datetime.combine(session_date + timedelta(days=1), time.min, tzinfo=WAT).astimezone(timezone.utc)
    return start, end


def load_journal(path: Path = JOURNAL) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if row.get("direction") in {"BUY", "SELL"} and row.get("signal_time"):
                rows.append(row)
        except json.JSONDecodeError:
            LOG.warning("Skipping malformed journal row %s", line_no)
    return rows


def _first_touch(signal: dict, candles: pd.DataFrame) -> dict:
    direction = signal["direction"]
    entry = float(signal["entry"])
    sl, tp1, tp2 = float(signal["sl"]), float(signal["tp1"]), float(signal["tp2"])
    stamp = pd.Timestamp(signal["signal_time"])
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    future = candles.loc[candles.index > stamp].sort_index()
    result = {"outcome": "UNRESOLVED", "first_touch": None, "bars_checked": int(len(future))}
    for ts, bar in future.iterrows():
        high, low = float(bar["High"]), float(bar["Low"])
        if direction == "BUY":
            hit_sl, hit_tp1, hit_tp2 = low <= sl, high >= tp1, high >= tp2
        else:
            hit_sl, hit_tp1, hit_tp2 = high >= sl, low <= tp1, low <= tp2
        # OHLC bars cannot reveal intrabar ordering. Conservatively count SL
        # first whenever SL and any target are both touched in one candle.
        if hit_sl and (hit_tp1 or hit_tp2):
            result.update(outcome="AMBIGUOUS_SL_FIRST", first_touch=ts.isoformat())
            return result
        if hit_sl:
            result.update(outcome="SL", first_touch=ts.isoformat())
            return result
        if hit_tp2:
            result.update(outcome="TP2", first_touch=ts.isoformat())
            return result
        if hit_tp1:
            result.update(outcome="TP1", first_touch=ts.isoformat())
            return result
    return result


def run(session_date: date) -> dict:
    start, end = session_bounds(session_date)
    journal = load_journal()
    universe = {m.name: m.symbol for m in MARKETS}
    for row in journal:
        name = row.get("market") or row.get("symbol")
        if name and name not in universe:
            ticker = SYMBOLS.get(name)
            if ticker:
                universe[name] = ticker

    OUT.mkdir(parents=True, exist_ok=True)
    coverage, outcomes = [], []
    frames: dict[str, pd.DataFrame] = {}
    for name, ticker in sorted(universe.items()):
        LOG.info("Downloading %s (%s)", name, ticker)
        frame = get_candles(ticker, start, end, interval="5m")
        if frame is None or frame.empty:
            coverage.append({"market": name, "ticker": ticker, "status": "NO_DATA", "m5_bars": 0})
            continue
        frame = frame.copy().sort_index()
        frame = frame.loc[(frame.index >= pd.Timestamp(start)) & (frame.index < pd.Timestamp(end))]
        frame.to_csv(OUT / f"{name.lower()}-m5.csv", index_label="timestamp")
        frames[name] = frame
        coverage.append({
            "market": name, "ticker": ticker, "status": "OK",
            "m5_bars": int(len(frame)), "first_utc": frame.index[0].isoformat(),
            "last_utc": frame.index[-1].isoformat(),
            "h1_bars_resampled": int(len(frame.resample("1h").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna())),
            "h4_bars_resampled": int(len(frame.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna())),
            "price_source": "Yahoo Finance OHLC research proxy; not executable BID/ASK",
        })

    for signal in journal:
        try:
            ts = pd.Timestamp(signal["signal_time"])
            ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
            local_date = ts.tz_convert(WAT).date()
            if local_date != session_date:
                continue
            market = signal.get("market") or signal.get("symbol")
            frame = frames.get(market)
            base = {
                "market": market, "symbol": signal.get("symbol"),
                "direction": signal["direction"], "signal_time": ts.isoformat(),
                "entry": signal.get("entry"), "sl": signal.get("sl"),
                "tp1": signal.get("tp1"), "tp2": signal.get("tp2"),
                "score": signal.get("score"), "setup": signal.get("setup"),
            }
            if frame is None:
                base.update(outcome="NO_DATA", first_touch=None, bars_checked=0)
            else:
                base.update(_first_touch(signal, frame))
            outcomes.append(base)
        except (KeyError, TypeError, ValueError) as exc:
            LOG.warning("Could not grade journal signal: %s", exc)

    report = {
        "session_date_wat": session_date.isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "session_start_utc": start.isoformat(), "session_end_utc": end.isoformat(),
        "universe_count": len(universe),
        "markets_with_data": sum(row["status"] == "OK" for row in coverage),
        "markets_without_data": [row["market"] for row in coverage if row["status"] != "OK"],
        "signals_in_session": len(outcomes),
        "outcomes": {key: sum(row["outcome"] == key for row in outcomes)
                     for key in ("TP1", "TP2", "SL", "AMBIGUOUS_SL_FIRST", "UNRESOLVED", "NO_DATA")},
        "execution_price_warning": "Yahoo OHLC does not provide broker BID/ASK. BUY/SELL outcomes are indicative only; do not treat this report as broker-grade settlement.",
        "coverage": coverage,
    }
    (OUT / "session-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (OUT / "signal-outcomes.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = sorted({key for row in outcomes for key in row})
        writer = csv.DictWriter(handle, fieldnames=fields)
        if fields:
            writer.writeheader()
            writer.writerows(outcomes)
    (OUT / "signal-outcomes.json").write_text(json.dumps(outcomes, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    requested = os.getenv("MERCURY_SESSION_DATE")
    day = date.fromisoformat(requested) if requested else datetime.now(WAT).date()
    summary = run(day)
    print(json.dumps({k: v for k, v in summary.items() if k != "coverage"}, indent=2))
