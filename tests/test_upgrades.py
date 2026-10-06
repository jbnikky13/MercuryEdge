import numpy as np
import pandas as pd

from mercuryedge.upgrades import (
    adx, htf_trend, passes_regime, currency_exposure,
    cap_exposure, select_setups, build_features,
    simulate_exit, compare_policies, make_candle_getter, walk_forward,
)


def _frame(n=1500, drift=0.0004):
    rng = np.random.default_rng(7)
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    close = 1.1 + np.cumsum(drift + rng.normal(0, 0.0003, n))
    wick = np.abs(rng.normal(0, 0.0004, n))
    return pd.DataFrame({
        "Open": close, "High": close + wick, "Low": close - wick, "Close": close,
    }, index=idx)


def test_regime_and_exposure():
    up = _frame()
    assert float(adx(up).iloc[-1]) > 20
    assert htf_trend(up) == "BUY"
    assert passes_regime(up, "BUY")[0]
    assert not passes_regime(up, "SELL")[0]

    assert currency_exposure("EURUSD=X", "BUY") == {"EUR": 1.0, "USD": -1.0}
    assert currency_exposure("GC=F", "BUY") == {"XAUUSD": 1.0, "USD": -0.5}
    picked = cap_exposure([
        {"symbol": "EURUSD", "direction": "BUY", "score": 80},
        {"symbol": "GBPUSD", "direction": "BUY", "score": 75},
        {"symbol": "USDJPY", "direction": "BUY", "score": 70},
    ])
    assert [x["symbol"] for x in picked] == ["EURUSD", "USDJPY"]


def test_selection_and_features():
    up = _frame()
    frames = {"EURUSD": up, "GBPUSD": up}
    candidates = [
        {"symbol": "EURUSD", "direction": "BUY", "score": 80},
        {"symbol": "GBPUSD", "direction": "BUY", "score": 75},
    ]
    final, skipped = select_setups(candidates, frames, max_setups=2)
    assert [x["symbol"] for x in final] == ["EURUSD"]
    assert any(x["reason"] == "exposure cap or beyond max_setups" for x in skipped)

    features = build_features("EURUSD", "BUY", 1.1, 1.095, 1.10575, 1.1115, 80, up)
    assert features["htf_agree"] is True
    assert features["rr_tp2"] is not None


def test_exit_and_walkforward():
    candles = pd.DataFrame(
        {"High": [101.2, 102.4], "Low": [100.1, 101.0], "Close": [101.0, 102.3]}
    )
    result = simulate_exit("BUY", 100, 99, 101.15, 102.3, candles, "half_be")
    assert abs(result - 1.725) < 1e-9

    frame = _frame()
    trades = [{
        "symbol": "EURUSD", "direction": "BUY", "entry": float(frame["Close"].iloc[400]),
        "sl": float(frame["Close"].iloc[400]) - 0.005,
        "tp1": float(frame["Close"].iloc[400]) + 0.00575,
        "tp2": float(frame["Close"].iloc[400]) + 0.0115,
        "ts": frame.index[400],
    }]
    per_trade, summary = compare_policies(trades, make_candle_getter({"EURUSD": frame}))
    assert len(per_trade) == 1
    assert "half_be" in summary.index

    rng = np.random.default_rng(7)
    rows = [{"ts": i, "score": rng.uniform(50, 100), "R": 1.15 if rng.random() < 0.5 else -1}
            for i in range(100)]
    assert walk_forward(pd.DataFrame(rows), "score", [55, 60, 65])["status"] == "ok"
