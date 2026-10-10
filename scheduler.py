"""Four daily MercuryEdge batch windows in Africa/Lagos; callable once per scheduled run."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from market_data import get_live_price
from signal_filters import filter_batch

TZ=ZoneInfo("Africa/Lagos")
SAME_SYMBOL_WINDOW_H=12
FOREX={"EURJPY","AUDJPY","GBPJPY","EURCHF","GBPCHF","EURGBP","EURUSD","GBPUSD","AUDUSD","NZDUSD","USDCAD","USDCHF","USDJPY","CADJPY"}
COMMODITIES={"XAUUSD","XAGUSD","NATGAS","UKOIL","USOIL","COPPER"}
INDICES={"SPX","DJI","RUSSELL2000","NASDAQ","VIX","DXY","US30","NAS100","SPX500"}
BATCHES=[
 ("OVERNIGHT",(1,30),FOREX|COMMODITIES),
 ("MORNING",(6,30),FOREX|COMMODITIES),
 ("AFTERNOON",(16,30),FOREX|COMMODITIES|INDICES),
 ("EVENING",(20,30),FOREX|COMMODITIES|INDICES),
]
def is_trading_day(now_local): return now_local.weekday()<5
def batch_for_time(now_local):
    now_local=now_local.astimezone(TZ)
    for name,(hour,minute),symbols in BATCHES:
        if (now_local.hour,now_local.minute)==(hour,minute): return name,symbols
    return None
def due_batch(now_local,last_run):
    for name,(h,m),symbols in BATCHES:
        start=now_local.replace(hour=h,minute=m,second=0,microsecond=0)
        if start<=now_local<start+timedelta(minutes=20) and last_run.get(name)!=start.date(): return name,start,symbols
    return None
def run_batch(name,symbols,now_utc,last_sent,generate_candidates,send_telegram):
    candidates=[c for c in generate_candidates(name) if c.get("symbol") in symbols]
    blocked={s:1 for s,t in last_sent.items() if now_utc-t<timedelta(hours=SAME_SYMBOL_WINDOW_H)}
    kept,dropped=filter_batch(candidates,price_lookup=get_live_price,already_sent_today=blocked)
    for sig,why in dropped: print(f"[{name}] DROPPED {sig.get('symbol')} {sig.get('direction')}: {why}")
    if not kept: print(f"[{name}] nothing passed the filter, sending nothing"); return []
    for sig in kept: sig["batch"]=name; last_sent[sig["symbol"]]=now_utc
    send_telegram(format_batch(name,kept)); return kept
def format_batch(name,signals):
    lines=[f"MERCURYEDGE • {name} • {len(signals)} SETUPS","-"*20]
    for i,s in enumerate(signals,1):
        lines.append(f"#{i} {s['direction']} {s['symbol']} @ {s['entry']}\nTP1 {s['tp1']}  TP2 {s['tp2']}  SL {s['sl']}\nScore {s['score']}  Plan: hold to TP2 or SL")
    lines.append("Paper/research signals only • MANAGE RISK")
    return "\n\n".join(lines)
