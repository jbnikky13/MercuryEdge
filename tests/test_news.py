from datetime import datetime, timezone

from mercuryedge import news


def test_nfp_feed_failure_is_explicitly_unavailable(monkeypatch):
    monkeypatch.setattr(news, "_parse_rss", lambda _url: None)
    result = news.nfp_risk(datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc))
    assert result.label == "NFP DATA UNAVAILABLE"
    assert result.data_available is False
    assert "unverified" in result.reason.lower()


def test_headline_only_does_not_claim_forecast_or_actual(monkeypatch):
    now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        news, "_parse_rss",
        lambda _url: [("US Nonfarm Payrolls preview", now)],
    )
    result = news.nfp_risk(now)
    assert result.high_impact is True
    assert result.data_available is True
    assert "Forecast/actual labor data: UNAVAILABLE" in result.reason


def test_successful_feed_without_headline_does_not_claim_calendar_verified(monkeypatch):
    monkeypatch.setattr(news, "_parse_rss", lambda _url: [("Market update", None)])
    result = news.nfp_risk(datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc))
    assert result.label == "NO NFP HEADLINE DETECTED"
    assert "does not verify the economic calendar" in result.reason


def test_signal_displays_unavailable_nfp_data_and_usd_exposure():
    from mercuryedge.signal import format_signal

    setup = {
        "historical_win_rate_3d": None,
        "direction": "BUY", "entry": 1.1, "tp1": 1.11, "tp2": 1.12,
        "sl": 1.09, "rr1": 1.0, "rr2": 2.0, "trend": "BULLISH",
        "setup": "TEST", "score": 70, "usd_exposed": True,
        "nfp_data_status": "FEED UNAVAILABLE",
        "nfp_data_reason": "NFP figures unverified.",
    }
    output = format_signal("EURUSD", "forex", setup)
    assert "USD EXPOSURE. YES" in output
    assert "NFP DATA STATUS. FEED UNAVAILABLE" in output
    assert "No forecast or actual labor figure is inferred" in output
