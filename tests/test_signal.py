from mercuryedge.signal import format_signal


def _setup(**overrides):
    setup = {
        "direction": "BUY", "entry": 1.1, "tp1": 1.10575, "tp2": 1.11125,
        "sl": 1.095, "rr1": 1.15, "rr2": 2.25, "trend": "BULLISH",
        "setup": "TREND CONTINUATION", "score": 78,
        "historical_win_rate_3d": 0.61, "historical_win_rate_1d": 0.58,
        "historical_win_rate_5d": 0.55, "holding_period": "INTRADAY_0_24H",
        "historical_samples": 64, "historical_regime": "TRENDING_UP",
        "historical_volatility": "LOWER_VOL", "historical_day": "Tuesday",
        "historical_month": 10, "historical_score": 4,
        "crossmarket_score": 3, "crossmarket_agreement": 0.75,
        "crossmarket_relationships": ["DXY inverse"], "adaptive_historical_modifier": 0,
        "adaptive_crossmarket_modifier": 0, "adaptive_agreement_modifier": 0,
        "regime_adx": 27.4, "regime_htf_trend": "BUY",
        "regime_htf_agree": True, "atr_pct": 0.42, "risk_pct": 0.63, "entry_stretch_atr": 1.37,
    }
    setup.update(overrides)
    return setup


def test_signal_shows_regime_and_risk_diagnostics():
    message = format_signal("EURUSD", "forex", _setup())
    assert "SETUP QUALITY CHECKS" in message
    assert "ADX. 27.4" in message
    assert "4H TREND. BUY / ALIGNED" in message
    assert "ATR VOLATILITY. 0.42% | STOP DISTANCE. 0.63%" in message
    assert "ENTRY STRETCH FROM EMA20. 1.37 ATR" in message
    assert "Quality gates: ADX, 4H trend alignment, currency exposure and duplicate/feed checks." in message


def test_signal_format_handles_missing_diagnostics():
    message = format_signal(
        "EURUSD", "forex",
        _setup(regime_adx=None, regime_htf_trend=None, regime_htf_agree=None,
               atr_pct=None, risk_pct=None, entry_stretch_atr=None),
    )
    assert "ADX. N/A" in message
    assert "ATR VOLATILITY / STOP DISTANCE. N/A" in message
    assert "ENTRY STRETCH FROM EMA20. N/A" in message
