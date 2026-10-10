"""Audited MercuryEdge quality gate and reproducible CSV backtest.

The thresholds are research safeguards fitted on a small sample, not guarantees.
Run: python signal_filters.py audit-results.csv
"""
import sys

MIN_SCORE = 65
MIN_HIT_RATE = 50.0
MIN_ANALOGUES = 40
MIN_CONFIRMATION = 0
MAX_FEED_DEVIATION = 0.02
MAX_PER_SYMBOL_PER_DAY = 1
BLOCK_RANGE_REGIME = False
PAUSED = {("VIX", "SELL"), ("DXY", "BUY")}


def check_signal(sig, price_lookup=None):
    """Return (accepted, reason). Missing/invalid evidence fails closed."""
    symbol = str(sig.get("symbol", "")).upper()
    direction = str(sig.get("direction", "")).upper()
    if (symbol, direction) in PAUSED:
        return False, "paused (poor audit record)"

    for key in ("score", "hit_rate", "analogues", "entry"):
        value = sig.get(key)
        if value is None:
            return False, f"missing required field: {key}"
        try:
            if value != value:  # NaN
                return False, f"missing required field: {key}"
        except (TypeError, ValueError):
            return False, f"invalid required field: {key}"

    try:
        score = float(sig["score"])
        hit_rate = float(sig["hit_rate"])
        analogues = int(float(sig["analogues"]))
        entry = float(sig["entry"])
    except (TypeError, ValueError, OverflowError):
        return False, "invalid score, hit rate, analogue count, or entry"
    if score < MIN_SCORE:
        return False, f"score {score:g} < {MIN_SCORE}"
    if hit_rate < MIN_HIT_RATE:
        return False, f"hit rate {hit_rate:g}% < {MIN_HIT_RATE}%"
    if analogues < MIN_ANALOGUES:
        return False, f"only {analogues} analogues"

    confirmation = sig.get("confirmation", 0)
    try:
        if confirmation is not None and float(confirmation) < MIN_CONFIRMATION:
            return False, f"cross-market confirmation {confirmation}"
    except (TypeError, ValueError):
        return False, "invalid cross-market confirmation"

    if BLOCK_RANGE_REGIME and str(sig.get("regime", "")).upper().startswith("RANGE"):
        return False, "range regime"

    if price_lookup is not None:
        try:
            live = price_lookup(symbol)
            if live is None or float(live) <= 0:
                return False, "no live price (data feed missing)"
            if abs(float(live) - entry) / float(live) > MAX_FEED_DEVIATION:
                return False, f"feed {live} vs entry {entry}"
        except Exception as exc:
            return False, f"price feed error: {exc}"
    return True, ""


def filter_batch(candidates, price_lookup=None, already_sent_today=None):
    """Keep highest-scoring eligible signal per symbol, preserving input dicts."""
    sent = {str(k).upper(): int(v) for k, v in (already_sent_today or {}).items()}
    kept, dropped = [], []
    def score_key(sig):
        try:
            return float(sig.get("score") or 0)
        except (TypeError, ValueError):
            return 0.0
    for sig in sorted(candidates, key=score_key, reverse=True):
        ok, why = check_signal(sig, price_lookup)
        symbol = str(sig.get("symbol", "")).upper()
        if ok and sent.get(symbol, 0) >= MAX_PER_SYMBOL_PER_DAY:
            ok, why = False, "symbol already sent today"
        if ok:
            sent[symbol] = sent.get(symbol, 0) + 1
            kept.append(sig)
        else:
            dropped.append((sig, why))
    return kept, dropped


def _r_value(row, rule):
    outcome = str(row.get("outcome", ""))
    back_to_entry = row.get("back_to_entry", 0)
    try:
        back_to_entry = int(float(back_to_entry)) if back_to_entry not in (None, "") else 0
    except (TypeError, ValueError):
        back_to_entry = 0
    if rule == "bank@TP1":
        return -1.0 if outcome == "SL" else 1.1
    if rule == "hold->TP2":
        return {"TP2": 2.2, "TP1_ONLY": 1.1}.get(outcome, -1.0)
    if rule == "half+BE":
        if outcome == "SL":
            return -1.0
        if back_to_entry == 1:
            return 0.55
        if outcome == "TP2":
            return 1.65
        return 1.1
    raise ValueError(f"unknown exit rule: {rule}")


def _backtest(path):
    import pandas as pd

    d = pd.read_csv(path).drop_duplicates("id")
    decided = {"SL", "TP2", "TP1_ONLY", "TP1_THEN_SL"}
    d = d[d["outcome"].isin(decided)].copy()
    if d.empty:
        print("No decided signals found in the audit CSV.")
        return

    d["day"] = d["ts_utc"].astype(str).str[:10]
    d["hold->TP2"] = d.apply(lambda row: _r_value(row, "hold->TP2"), axis=1)
    d["bank@TP1"] = d.apply(lambda row: _r_value(row, "bank@TP1"), axis=1)
    d["half+BE"] = d.apply(lambda row: _r_value(row, "half+BE"), axis=1)

    kept_ids = set()
    for _, group in d.groupby("day", sort=True):
        candidates = group.to_dict("records")
        for candidate in candidates:
            candidate["_i"] = candidate["id"]
        kept, _ = filter_batch(candidates)
        kept_ids.update(candidate["_i"] for candidate in kept)

    for label, frame in (
        ("unfiltered", d),
        ("filtered", d[d["id"].isin(kept_ids)]),
    ):
        if frame.empty:
            print(f"{label:10s} n=0 (no qualifying signals)")
            continue
        sl_pct = (frame["outcome"] == "SL").mean() * 100
        means = "  ".join(f"{rule} {frame[rule].mean():5.2f}R" for rule in ("bank@TP1", "hold->TP2", "half+BE"))
        print(f"{label:10s} n={len(frame):3d} SL {sl_pct:3.0f}%  {means}")


if __name__ == "__main__":
    _backtest(sys.argv[1] if len(sys.argv) > 1 else "audit-results.csv")
