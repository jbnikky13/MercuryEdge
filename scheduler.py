"""
Batch definitions shared by MercuryEdge's GitHub Actions entry point and the
optional long-running scheduler. Times are Africa/Lagos local time.
"""
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_data import get_live_price
from signal_filters import filter_batch

TZ = ZoneInfo("Africa/Lagos")
SAME_SYMBOL_WINDOW_H = 12

FOREX = {
    "EURJPY", "AUDJPY", "GBPJPY", "EURCHF", "GBPCHF", "EURGBP",
    "EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF",
    "USDJPY", "CADJPY",
}
COMMODITIES = {"XAUUSD", "XAGUSD", "NATGAS", "UKOIL", "USOIL", "COPPER"}
INDICES = {"SPX", "DJI", "RUSSELL2000", "NASDAQ", "VIX", "DXY"}

BATCHES = [
    ("OVERNIGHT", (1, 30), FOREX | COMMODITIES),
    ("MORNING",   (6, 30), FOREX | COMMODITIES),
    ("AFTERNOON", (16, 30), FOREX | COMMODITIES | INDICES),
    ("EVENING",   (20, 30), FOREX | COMMODITIES | INDICES),
]


def is_trading_day(now_local):
    return now_local.weekday() < 5


def due_batch(now_local, last_run):
    """Return a batch during its 20-minute window, at most once per local date."""
    for name, (hour, minute), symbols in BATCHES:
        start = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start <= now_local < start + timedelta(minutes=20):
            if last_run.get(name) != start.date():
                return name, start, symbols
    return None


def run_batch(name, symbols, now_utc, last_sent, generate_candidates, send_telegram):
    candidates = [c for c in generate_candidates(name) if c.get("symbol") in symbols]
    blocked = {
        symbol: 1 for symbol, sent_at in last_sent.items()
        if now_utc - sent_at < timedelta(hours=SAME_SYMBOL_WINDOW_H)
    }
    kept, dropped = filter_batch(
        candidates, price_lookup=get_live_price, already_sent_today=blocked
    )
    for sig, reason in dropped:
        print(f"[{name}] DROPPED {sig.get('symbol')} {sig.get('direction')}: {reason}")
    if not kept:
        print(f"[{name}] nothing passed the filter, sending nothing")
        return []

    for sig in kept:
        sig["batch"] = name
        last_sent[sig["symbol"]] = now_utc
    send_telegram(format_batch(name, kept))
    return kept


def format_batch(name, signals):
    lines = [f"MERCURYEDGE • {name} • {len(signals)} SETUPS", "-" * 20]
    for index, sig in enumerate(signals, 1):
        lines.append(
            f"#{index} {sig['direction']} {sig['symbol']} @ {sig['entry']}\n"
            f"TP1 {sig['tp1']}  TP2 {sig['tp2']}  SL {sig['sl']}\n"
            f"Score {sig['score']}  Plan: hold to TP2 or SL"
        )
    lines.append("Paper/research signals only • MANAGE RISK")
    return "\n\n".join(lines)


def main(generate_candidates, send_telegram):
    last_run, last_sent = {}, {}
    while True:
        now_local = datetime.now(TZ)
        if is_trading_day(now_local):
            due = due_batch(now_local, last_run)
            if due:
                name, start, symbols = due
                last_run[name] = start.date()
                try:
                    run_batch(
                        name, symbols, datetime.now(ZoneInfo("UTC")),
                        last_sent, generate_candidates, send_telegram,
                    )
                except Exception as exc:
                    send_telegram(f"{name} batch failed: {exc}")
        time.sleep(30)


if __name__ == "__main__":
    def generate_candidates(batch_name):
        return []  # Replace with the real signal-engine adapter.

    def send_telegram(message):
        print(message)

    main(generate_candidates, send_telegram)
