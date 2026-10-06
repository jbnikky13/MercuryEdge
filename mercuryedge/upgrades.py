from __future__ import annotations

import math
from typing import Callable

import numpy as np
import pandas as pd


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)
    out.columns = [str(c).lower() for c in out.columns]
    return out


def _get(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _side(direction) -> int:
    value = str(getattr(direction, "value", direction)).strip().upper()
    if value in {"BUY", "LONG", "1", "+1"}:
        return 1
    if value in {"SELL", "SHORT", "-1"}:
        return -1
    raise ValueError(f"Unknown direction: {direction!r}")


def _f(value, nd: int = 6):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return round(value, nd) if math.isfinite(value) else None


def _to_utc(ts) -> pd.Timestamp:
    value = pd.Timestamp(ts)
    return value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    d = _norm(df)
    h, l, c = d["high"], d["low"], d["close"]
    tr = pd.concat(
        [(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    d = _norm(df)
    h, l, c = d["high"], d["low"], d["close"]
    up, down = h.diff(), -l.diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=d.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=d.index)
    tr = pd.concat(
        [(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1
    ).max(axis=1)
    alpha = 1.0 / n
    tr_s = tr.ewm(alpha=alpha, adjust=False).mean()
    pdi = 100 * plus.ewm(alpha=alpha, adjust=False).mean() / tr_s
    mdi = 100 * minus.ewm(alpha=alpha, adjust=False).mean() / tr_s
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=alpha, adjust=False).mean()


def htf_trend(df_1h: pd.DataFrame, fast: int = 50, slow: int = 200):
    d = _norm(df_1h)
    if not isinstance(d.index, pd.DatetimeIndex):
        return None
    d = d.sort_index()
    h4 = d["close"].resample("4h").last().dropna()
    if len(h4) < slow + 10:
        return None
    fast_ema = h4.ewm(span=fast, adjust=False).mean().iloc[-1]
    slow_ema = h4.ewm(span=slow, adjust=False).mean().iloc[-1]
    return "BUY" if fast_ema > slow_ema else "SELL"


def passes_regime(
    df_1h: pd.DataFrame,
    direction,
    min_adx: float = 20.0,
    require_htf: bool = True,
):
    side = "BUY" if _side(direction) == 1 else "SELL"
    adx_series = adx(df_1h)
    adx_now = float(adx_series.iloc[-1])
    htf = htf_trend(df_1h)
    reasons = []
    if not np.isfinite(adx_now) or adx_now < min_adx:
        reasons.append(f"ADX {adx_now:.1f} < {min_adx:g}")
    if require_htf and htf != side:
        reasons.append(f"4h trend {htf or 'unknown'} vs {side}")
    return not reasons, {
        "adx": adx_now,
        "htf_trend": htf,
        "htf_agree": htf == side,
        "reasons": reasons,
    }


COMMODITY_USD_WEIGHT = 0.5
_USD_PRICED = {"USOIL", "UKOIL", "NATGAS", "COPPER", "XAUUSD", "XAGUSD"}
_YF_TO_NAME = {
    "GC=F": "XAUUSD",
    "SI=F": "XAGUSD",
    "CL=F": "USOIL",
    "BZ=F": "UKOIL",
    "NG=F": "NATGAS",
    "HG=F": "COPPER",
    "DX-Y.NYB": "DXY",
    "DX=F": "DXY",
}


def currency_exposure(symbol: str, direction) -> dict:
    raw = str(symbol).upper().replace("/", "")
    sym = _YF_TO_NAME.get(raw, raw.replace("=X", ""))
    side = _side(direction)

    if sym == "DXY":
        return {"USD": float(side)}
    if sym in _USD_PRICED:
        return {sym: float(side), "USD": -side * COMMODITY_USD_WEIGHT}
    if len(sym) == 6 and sym.isalpha():
        return {sym[:3]: float(side), sym[3:]: float(-side)}
    return {sym: float(side)}


def cap_exposure(
    setups,
    max_per_ccy: float = 1.0,
    existing=None,
    limit: int | None = None,
) -> list:
    book: dict[str, float] = {}
    for item in existing or []:
        symbol = _get(item, "symbol") or _get(item, "market")
        direction = _get(item, "direction")
        if not symbol or not direction:
            continue
        for ccy, value in currency_exposure(symbol, direction).items():
            book[ccy] = book.get(ccy, 0.0) + value

    chosen = []
    for setup in sorted(setups, key=lambda x: -float(_get(x, "score", 0) or 0)):
        exposure = currency_exposure(_get(setup, "symbol"), _get(setup, "direction"))
        blocked = any(
            abs(book.get(ccy, 0.0) + value) > max_per_ccy + 1e-9
            and abs(book.get(ccy, 0.0) + value) > abs(book.get(ccy, 0.0)) + 1e-9
            for ccy, value in exposure.items()
        )
        if blocked:
            continue
        for ccy, value in exposure.items():
            book[ccy] = book.get(ccy, 0.0) + value
        chosen.append(setup)
        if limit is not None and len(chosen) >= limit:
            break
    return chosen


def select_setups(
    setups,
    frames: dict,
    max_setups: int = 4,
    existing=None,
    min_adx: float = 20.0,
    require_htf: bool = True,
    max_per_ccy: float = 1.0,
):
    passed, skipped = [], []
    for setup in setups:
        symbol, direction = _get(setup, "symbol"), _get(setup, "direction")
        frame = frames.get(symbol)
        if frame is None or len(frame) < 60:
            skipped.append({
                "symbol": symbol,
                "direction": str(direction),
                "reason": "no / too little candle data",
            })
            continue
        try:
            ok, info = passes_regime(frame, direction, min_adx, require_htf)
        except (KeyError, ValueError, IndexError) as exc:
            skipped.append({
                "symbol": symbol,
                "direction": str(direction),
                "reason": f"regime calculation failed: {exc}",
            })
            continue
        if ok:
            passed.append(setup)
        else:
            skipped.append({
                "symbol": symbol,
                "direction": str(direction),
                "reason": "; ".join(info["reasons"]),
            })

    final = cap_exposure(passed, max_per_ccy, existing, limit=max_setups)
    kept_ids = {id(item) for item in final}
    for setup in passed:
        if id(setup) not in kept_ids:
            skipped.append({
                "symbol": _get(setup, "symbol"),
                "direction": str(_get(setup, "direction")),
                "reason": "exposure cap or beyond max_setups",
            })
    return final, skipped


def build_features(
    symbol: str,
    direction,
    entry: float,
    sl: float,
    tp1: float,
    tp2: float,
    score,
    df_1h: pd.DataFrame,
    ts=None,
    components: dict | None = None,
    min_adx: float = 20.0,
) -> dict:
    d = _norm(df_1h)
    t = _to_utc(ts if ts is not None else d.index[-1])
    price = float(d["close"].iloc[-1])
    risk = abs(float(entry) - float(sl))
    _, info = passes_regime(df_1h, direction, min_adx)
    result = {
        "score": _f(score),
        "adx": _f(info["adx"], 2),
        "htf_trend": info["htf_trend"],
        "htf_agree": bool(info["htf_agree"]),
        "atr_pct": _f(atr(df_1h).iloc[-1] / price * 100, 4) if price else None,
        "risk_pct": _f(risk / float(entry) * 100, 4) if entry else None,
        "rr_tp1": _f(abs(float(tp1) - float(entry)) / risk, 3) if risk else None,
        "rr_tp2": _f(abs(float(tp2) - float(entry)) / risk, 3) if risk else None,
        "hour_utc": int(t.hour),
        "weekday": int(t.weekday()),
        "ccy_exposure": currency_exposure(symbol, direction),
    }
    if components:
        result["score_components"] = {key: _f(value) for key, value in components.items()}
    return result


POLICIES = {
    "tp1_full": (1.0, 0.0, False),
    "tp2_full": (0.0, 1.0, False),
    "half_be": (0.5, 0.5, True),
    "half_sl": (0.5, 0.5, False),
}


def simulate_exit(
    direction,
    entry: float,
    sl: float,
    tp1: float,
    tp2: float,
    candles: pd.DataFrame,
    policy: str = "half_be",
    horizon: int | None = 24,
    expiry: str = "mark",
):
    if policy not in POLICIES:
        raise ValueError(f"Unknown exit policy: {policy}")
    w1, _w2, move_to_be = POLICIES[policy]
    side = _side(direction)
    risk = abs(entry - sl)
    c = _norm(candles)
    if horizon:
        c = c.iloc[:horizon]
    if risk == 0 or c.empty:
        return None

    r1 = side * (tp1 - entry) / risk
    r2 = side * (tp2 - entry) / risk
    stop, banked, left, tp1_done = sl, 0.0, 1.0, False

    for high, low in zip(c["high"].to_numpy(), c["low"].to_numpy()):
        adverse, favour = (low, high) if side == 1 else (high, low)
        hit_stop = adverse <= stop if side == 1 else adverse >= stop
        hit_tp1 = favour >= tp1 if side == 1 else favour <= tp1
        hit_tp2 = favour >= tp2 if side == 1 else favour <= tp2

        if hit_stop:
            return banked + left * side * (stop - entry) / risk

        if not tp1_done and hit_tp1:
            tp1_done = True
            banked += w1 * r1
            left = 1.0 - w1
            if left <= 1e-12:
                return banked
            if move_to_be:
                stop = entry

        if tp1_done and hit_tp2:
            return banked + left * r2

    mark = 0.0 if expiry == "flat" else side * (float(c["close"].iloc[-1]) - entry) / risk
    return banked + left * mark


def bootstrap_ci(values, n_boot: int = 5000, alpha: float = 0.05, seed: int = 7):
    x = np.asarray(
        [v for v in values if v is not None and not np.isnan(v)], dtype=float
    )
    if len(x) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = rng.choice(x, size=(n_boot, len(x)), replace=True).mean(axis=1)
    return tuple(float(v) for v in np.quantile(means, [alpha / 2, 1 - alpha / 2]))


def _align_ts(ts, index: pd.DatetimeIndex) -> pd.Timestamp:
    value = _to_utc(ts)
    return value.tz_localize(None) if index.tz is None else value.tz_convert(index.tz)


def make_candle_getter(frames: dict) -> Callable:
    def get(symbol, ts, horizon):
        frame = frames.get(symbol)
        if frame is None:
            return None
        d = _norm(frame)
        return d[d.index > _align_ts(ts, d.index)].iloc[:horizon]
    return get


def compare_policies(
    trades,
    get_candles: Callable,
    horizon: int = 24,
    policies=None,
    expiry: str = "mark",
):
    pols = list(policies or POLICIES)
    records = trades.to_dict("records") if hasattr(trades, "to_dict") else list(trades)
    rows = []
    for trade in records:
        candles = get_candles(trade["symbol"], trade["ts"], horizon)
        if candles is None or len(candles) == 0:
            continue
        row = {"symbol": trade["symbol"], "ts": trade["ts"]}
        for policy in pols:
            row[policy] = simulate_exit(
                trade["direction"], trade["entry"], trade["sl"],
                trade["tp1"], trade["tp2"], candles, policy, horizon, expiry
            )
        rows.append(row)

    per_trade = pd.DataFrame(rows)
    if per_trade.empty:
        return per_trade, pd.DataFrame()

    summary = []
    for policy in pols:
        values = per_trade[policy].dropna()
        lo, hi = bootstrap_ci(values)
        summary.append({
            "policy": policy,
            "n": int(len(values)),
            "win_%": round(100 * float((values > 0).mean()), 1) if len(values) else float("nan"),
            "avg_R": round(float(values.mean()), 3),
            "total_R": round(float(values.sum()), 2),
            "avg_R_95lo": round(lo, 3),
            "avg_R_95hi": round(hi, 3),
        })
    return per_trade, pd.DataFrame(summary).set_index("policy")


def walk_forward(
    df: pd.DataFrame,
    feature: str,
    thresholds,
    r_col: str = "R",
    time_col: str = "ts",
    train: int = 60,
    test: int = 20,
    direction: str = "ge",
    min_keep: int = 15,
) -> dict:
    data = df.dropna(subset=[feature, r_col]).copy()
    if time_col in data.columns:
        data = data.sort_values(time_col)
    data = data.reset_index(drop=True)
    if len(data) < train + test:
        return {"status": "insufficient_data", "have": len(data), "need": train + test}

    keep = (lambda values, threshold: values >= threshold) if direction == "ge" else (
        lambda values, threshold: values <= threshold
    )
    baseline_r, filtered_r, selected_thresholds = [], [], []

    for start in range(train, len(data) - test + 1, test):
        train_df = data.iloc[start - train:start]
        test_df = data.iloc[start:start + test]
        best_threshold, best_mean = None, -np.inf
        for threshold in thresholds:
            mask = keep(train_df[feature], threshold)
            if int(mask.sum()) >= min_keep:
                mean_r = float(train_df.loc[mask, r_col].mean())
                if mean_r > best_mean:
                    best_threshold, best_mean = threshold, mean_r
        baseline_r.extend(test_df[r_col].tolist())
        selected = test_df[keep(test_df[feature], best_threshold)] if best_threshold is not None else test_df
        filtered_r.extend(selected[r_col].tolist())
        selected_thresholds.append(best_threshold)

    def stats(values):
        return {
            "n": len(values),
            "total_R": round(float(sum(values)), 2),
            "avg_R": round(float(np.mean(values)), 3) if values else None,
        }

    return {
        "status": "ok",
        "windows": len(selected_thresholds),
        "thresholds_chosen": selected_thresholds,
        "baseline": stats(baseline_r),
        "filtered": stats(filtered_r),
    }
