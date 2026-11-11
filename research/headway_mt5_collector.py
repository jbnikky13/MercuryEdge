"""Read-only collector for Headway MT5 demo quotes.

Run on a Windows host with the official MT5 desktop terminal installed and
already logged in to a Headway-Demo account. This module deliberately exposes
no order-placement or account-mutation operations.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

LOG = logging.getLogger("mercuryedge.headway")
WAT = ZoneInfo("Africa/Lagos")
EXPECTED_SERVER = "headway-demo"
EXPECTED_SERVER_HOST = "mt5.demo.trade-hw.online"
DEFAULT_SYMBOLS = (
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD",
    "USDCAD", "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "CADJPY",
    "EURCHF", "GBPCHF", "XAUUSD", "XAGUSD", "USOIL", "UKOIL",
    "NATGAS", "COPPER", "SPX", "DJI", "NASDAQ", "RUSSELL2000",
    "VIX", "DXY",
)
TIMEFRAMES = ("M1", "M5", "H1", "H4")


class FeedError(RuntimeError):
    pass


def _normal(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def session_bounds(session_day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(session_day, time.min, tzinfo=WAT).astimezone(timezone.utc)
    end = datetime.combine(session_day + timedelta(days=1), time.min, tzinfo=WAT).astimezone(timezone.utc)
    return start, end


def resolve_symbol(mt5, requested: str) -> tuple[str | None, str]:
    """Resolve exact broker symbol first; accept a suffix only when unique."""
    available = list(mt5.symbols_get() or [])
    by_normal = {_normal(item.name): item.name for item in available}
    key = _normal(requested)
    if key in by_normal:
        return by_normal[key], "exact"
    suffixed = sorted(item.name for item in available if _normal(item.name).startswith(key))
    if len(suffixed) == 1:
        return suffixed[0], "unique_suffix"
    if len(suffixed) > 1:
        return None, "ambiguous:" + ",".join(suffixed)
    return None, "not_found"


def _write_csv(path: Path, rows, fieldnames: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))
            count += 1
    return count


def _tick_rows(mt5, symbol: str, start: datetime, end: datetime):
    """Fetch in 15-minute windows to bound memory; remove inclusive-edge duplicates."""
    cursor = start
    seen = set()
    while cursor < end:
        window_end = min(cursor + timedelta(minutes=15), end)
        ticks = mt5.copy_ticks_range(symbol, cursor, window_end, mt5.COPY_TICKS_ALL)
        if ticks is None:
            raise FeedError(f"Tick history request failed for {symbol}: {mt5.last_error()}")
        for tick in ticks:
            row = {
                "time_msc": int(tick["time_msc"]),
                "time_utc": datetime.fromtimestamp(int(tick["time_msc"]) / 1000, timezone.utc).isoformat(),
                "bid": float(tick["bid"]),
                "ask": float(tick["ask"]),
                "last": float(tick["last"]),
                "volume": float(tick["volume"]),
                "flags": int(tick["flags"]),
            }
            key = (row["time_msc"], row["bid"], row["ask"], row["last"], row["flags"])
            if key not in seen:
                seen.add(key)
                yield row
        cursor = window_end


def collect(session_day: date, requested_symbols=DEFAULT_SYMBOLS, output_root=Path("research_data/headway_mt5"), mt5=None) -> dict:
    if mt5 is None:
        if sys.platform != "win32":
            raise FeedError("The official MetaTrader5 Python package requires a Windows host with the desktop MT5 terminal.")
        try:
            import MetaTrader5 as mt5_module
        except ImportError as exc:
            raise FeedError("Install the official MetaTrader5 Python package on the Windows MT5 host.") from exc
        mt5 = mt5_module

    if not mt5.initialize():
        raise FeedError(f"Could not initialize the local MT5 terminal: {mt5.last_error()}")
    try:
        terminal = mt5.terminal_info()
        account = mt5.account_info()
        if terminal is None or account is None:
            raise FeedError(f"MT5 terminal/account unavailable: {mt5.last_error()}")
        server = str(account.server or "")
        if _normal(server) != _normal(EXPECTED_SERVER):
            raise FeedError(f"Wrong MT5 server '{server}'. Expected Headway-Demo; refusing to collect.")
        if int(account.trade_mode) != int(mt5.ACCOUNT_TRADE_MODE_DEMO):
            raise FeedError("The connected account is not marked DEMO by MT5; refusing to collect.")
        if not bool(terminal.connected):
            raise FeedError("MT5 terminal is not connected to the broker.")

        start, end = session_bounds(session_day)
        out = Path(output_root) / session_day.isoformat()
        out.mkdir(parents=True, exist_ok=True)
        symbol_report = []
        totals = {"ticks": 0, "bars": 0}
        for requested in requested_symbols:
            broker_symbol, resolution = resolve_symbol(mt5, requested)
            if broker_symbol is None:
                symbol_report.append({"requested": requested, "status": "SYMBOL_UNRESOLVED", "resolution": resolution})
                continue
            if not mt5.symbol_select(broker_symbol, True):
                symbol_report.append({"requested": requested, "broker_symbol": broker_symbol, "status": "SYMBOL_SELECT_FAILED"})
                continue
            info = mt5.symbol_info(broker_symbol)
            if info is None:
                symbol_report.append({"requested": requested, "broker_symbol": broker_symbol, "status": "NO_SYMBOL_INFO"})
                continue

            symbol_dir = out / broker_symbol
            tick_fields = ["time_msc", "time_utc", "bid", "ask", "last", "volume", "flags"]
            tick_count = _write_csv(symbol_dir / "ticks.csv", _tick_rows(mt5, broker_symbol, start, end), tick_fields)
            timeframe_counts = {}
            for timeframe_name in TIMEFRAMES:
                timeframe = getattr(mt5, f"TIMEFRAME_{timeframe_name}")
                rates = mt5.copy_rates_range(broker_symbol, timeframe, start, end)
                if rates is None:
                    raise FeedError(f"Rate history request failed for {broker_symbol}/{timeframe_name}: {mt5.last_error()}")
                rows = []
                for rate in rates:
                    stamp = datetime.fromtimestamp(int(rate["time"]), timezone.utc)
                    rows.append({
                        "time_utc": stamp.isoformat(), "open": float(rate["open"]),
                        "high": float(rate["high"]), "low": float(rate["low"]),
                        "close": float(rate["close"]), "tick_volume": int(rate["tick_volume"]),
                        "spread_points": int(rate["spread"]), "real_volume": int(rate["real_volume"]),
                    })
                timeframe_counts[timeframe_name] = _write_csv(
                    symbol_dir / f"{timeframe_name.lower()}.csv", rows,
                    ["time_utc", "open", "high", "low", "close", "tick_volume", "spread_points", "real_volume"],
                )
            totals["ticks"] += tick_count
            totals["bars"] += sum(timeframe_counts.values())
            symbol_report.append({
                "requested": requested, "broker_symbol": broker_symbol, "resolution": resolution,
                "status": "OK", "ticks": tick_count, "bars": timeframe_counts,
                "digits": int(info.digits), "point": float(info.point),
                "trade_contract_size": float(info.trade_contract_size),
                "volume_min": float(info.volume_min), "volume_step": float(info.volume_step),
                "spread_points_snapshot": int(info.spread),
                "bid_snapshot": float(info.bid), "ask_snapshot": float(info.ask),
                "trade_tick_size": float(info.trade_tick_size),
                "trade_tick_value": float(info.trade_tick_value),
            })

        report = {
            "session_date_wat": session_day.isoformat(),
            "collected_at_utc": datetime.now(timezone.utc).isoformat(),
            "server": server, "server_host_reference": EXPECTED_SERVER_HOST,
            "account_mode": "DEMO", "read_only": True,
            "terminal_build": int(terminal.build),
            "session_start_utc": start.isoformat(), "session_end_utc": end.isoformat(),
            "requested_symbols": len(requested_symbols), "symbols": symbol_report,
            "totals": totals,
            "limitations": [
                "Feed data are Headway demo-server quotes, not guaranteed identical to future live-account quotes.",
                "Historical MT5 ticks are limited to the history made available by the broker/server.",
                "OHLC candles cannot determine intrabar TP/SL ordering; tick replay is required.",
                "A quote touching a level is not proof of a real order fill.",
            ],
        }
        (out / "feed-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report
    finally:
        mt5.shutdown()


def main():
    parser = argparse.ArgumentParser(description="Read-only Headway MT5 demo market-data collector")
    parser.add_argument("--date", help="Completed Africa/Lagos session date (YYYY-MM-DD); default yesterday")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="Comma-separated canonical MercuryEdge symbols")
    parser.add_argument("--output", default="research_data/headway_mt5")
    args = parser.parse_args()
    day = date.fromisoformat(args.date) if args.date else datetime.now(WAT).date() - timedelta(days=1)
    report = collect(day, [x.strip() for x in args.symbols.split(",") if x.strip()], Path(args.output))
    print(json.dumps({"session_date_wat": report["session_date_wat"], "server": report["server"], "totals": report["totals"], "symbols": report["symbols"]}, indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
