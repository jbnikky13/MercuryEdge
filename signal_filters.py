"""Audited quality gate. Thresholds are research heuristics, not a guarantee."""
MIN_SCORE=65
MIN_HIT_RATE=50.0
MIN_ANALOGUES=40
MIN_CONFIRMATION=0
MAX_FEED_DEVIATION=0.02
MAX_PER_SYMBOL_PER_DAY=1
BLOCK_RANGE_REGIME=False
PAUSED={("VIX","SELL"),("DXY","BUY")}

def check_signal(sig, price_lookup=None):
    symbol=str(sig["symbol"]).upper()
    direction=str(sig["direction"]).upper()
    if (symbol,direction) in PAUSED: return False,"paused (poor audit record)"
    for key in ("score","hit_rate","analogues","entry"):
        if sig.get(key) is None: return False,f"missing required field: {key}"
    if float(sig["score"])<MIN_SCORE: return False,f"score {sig['score']} < {MIN_SCORE}"
    if float(sig["hit_rate"])<MIN_HIT_RATE: return False,f"hit rate {sig['hit_rate']}% < {MIN_HIT_RATE}%"
    if int(sig["analogues"])<MIN_ANALOGUES: return False,f"only {sig['analogues']} analogues"
    confirmation=sig.get("confirmation",0)
    if confirmation is not None and float(confirmation)<MIN_CONFIRMATION: return False,f"cross-market confirmation {confirmation}"
    if BLOCK_RANGE_REGIME and str(sig.get("regime","")).startswith("RANGE"): return False,"range regime"
    if price_lookup is not None:
        live=price_lookup(symbol)
        if live is None: return False,"no live price (data feed missing)"
        if abs(float(live)-float(sig["entry"]))/float(live)>MAX_FEED_DEVIATION: return False,f"feed {live} vs entry {sig['entry']}"
    return True,""

def filter_batch(candidates, price_lookup=None, already_sent_today=None):
    sent=dict(already_sent_today or {})
    kept,dropped=[],[]
    for sig in sorted(candidates,key=lambda s:float(s.get("score") or 0),reverse=True):
        ok,why=check_signal(sig,price_lookup)
        symbol=str(sig.get("symbol","")).upper()
        if ok and sent.get(symbol,0)>=MAX_PER_SYMBOL_PER_DAY: ok,why=False,"symbol already sent today"
        if ok:
            sent[symbol]=sent.get(symbol,0)+1; kept.append(sig)
        else: dropped.append((sig,why))
    return kept,dropped
