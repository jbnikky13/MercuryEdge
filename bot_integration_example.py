"""Example integration of the quality gate into a signal batch."""
from market_data import get_live_price, health_check
from signal_filters import filter_batch

SENT_TODAY = {}

def build_and_send_batch(candidates, send_telegram):
    kept, dropped = filter_batch(candidates, price_lookup=get_live_price,
                                 already_sent_today=SENT_TODAY)
    for sig, why in dropped:
        print(f"DROPPED {sig['symbol']} {sig['direction']}: {why}")
    if not kept:
        return
    for sig in kept:
        SENT_TODAY[sig["symbol"]] = SENT_TODAY.get(sig["symbol"], 0) + 1
    send_telegram(format_batch(kept))

def format_batch(signals):
    lines = [f"MERCURYEDGE • {len(signals)} SETUPS", "-" * 20]
    for i, s in enumerate(signals, 1):
        lines.append(
            f"#{i} {s['direction']} {s['symbol']} @ {s['entry']}\n"
            f"TP1 {s['tp1']}  TP2 {s['tp2']}  SL {s['sl']}\n"
            f"Score {s['score']}  Plan: hold to TP2 or SL"
        )
    lines.append("Paper/research signals only • MANAGE RISK")
    return "\n\n".join(lines)

def reset_daily():
    SENT_TODAY.clear()

def morning_health_check(send_telegram):
    bad = health_check()
    if bad:
        send_telegram("DATA FEED PROBLEM: no data for " + ", ".join(bad))
