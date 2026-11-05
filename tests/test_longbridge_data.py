import json
import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace

from mercuryedge import longbridge_data as lb


SAMPLE_QUOTE = {
    "symbol": "NVDA.US",
    "last": "182.660",
    "change_value": "-17.470",
    "change_percentage": "-8.73",
    "prev_close": "200.130",
    "open": "196.000",
    "high": "196.250",
    "low": "181.550",
    "volume": 190953992,
    "turnover": "35710130213.446",
    "status": "Normal",
    "post_market": {
        "last": "199.800",
        "timestamp": "2026-11-05T00:59:59Z",
        "high": "201.930",
        "low": "199.617",
        "volume": 5609574,
        "turnover": "1123923057.558",
        "prev_close": "200.130",
    },
    "overnight": {
        "last": "199.190",
        "timestamp": "2026-11-05T09:00:00Z",
    },
    "pre_market": {
        "last": "196.150",
        "timestamp": "2026-11-05T14:30:01Z",
    },
}


def test_configured_symbols_deduplicates_and_normalizes(monkeypatch):
    monkeypatch.setenv(
        "MERCURY_LONGBRIDGE_SYMBOLS",
        " nvda.us, AAPL.US,NVDA.US ,,",
    )
    assert lb.configured_symbols() == ["NVDA.US", "AAPL.US"]


def test_normalize_quote_preserves_extended_sessions():
    observed = datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc)
    result = lb.normalize_quote(SAMPLE_QUOTE, observed_at=observed)

    assert result["symbol"] == "NVDA.US"
    assert result["last"] == "182.660"
    assert result["previous_close"] == "200.130"
    assert result["trade_status"] == "Normal"
    assert result["volume"] == 190953992
    assert result["observed_at_utc"] == "2026-11-05T14:00:00+00:00"
    assert "not exchange event time" in result["timestamp_type"]
    assert result["source"] == "Longbridge CLI"
    assert result["pre_market"]["timestamp"] == "2026-11-05T14:30:01Z"
    assert result["post_market"]["last"] == "199.800"
    assert result["overnight"]["last"] == "199.190"


def test_fetch_quotes_is_disabled_without_symbols(monkeypatch):
    monkeypatch.delenv("MERCURY_LONGBRIDGE_SYMBOLS", raising=False)
    assert lb.fetch_quotes() == []


def test_fetch_quotes_fails_closed_when_cli_missing(monkeypatch):
    monkeypatch.setattr(lb.shutil, "which", lambda _name: None)
    assert lb.fetch_quotes(["NVDA.US"]) == []


def test_fetch_quotes_runs_cli_and_parses_json(monkeypatch):
    monkeypatch.setattr(lb.shutil, "which", lambda _name: "/usr/bin/longbridge")

    calls = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps([SAMPLE_QUOTE]),
            stderr="",
        )

    monkeypatch.setattr(lb.subprocess, "run", fake_run)

    result = lb.fetch_quotes(["nvda.us"])

    assert calls["command"] == [
        "/usr/bin/longbridge",
        "quote",
        "NVDA.US",
        "--format",
        "json",
    ]
    assert calls["kwargs"]["timeout"] == lb.CLI_TIMEOUT_SECONDS
    assert result[0]["symbol"] == "NVDA.US"


def test_fetch_quotes_rejects_option_like_symbol_before_cli(monkeypatch):
    cli_called = False

    def fake_run(*_args, **_kwargs):
        nonlocal cli_called
        cli_called = True
        raise AssertionError("CLI must not be called for an option-like symbol")

    monkeypatch.setattr(lb.shutil, "which", lambda _name: "/usr/bin/longbridge")
    monkeypatch.setattr(lb.subprocess, "run", fake_run)

    assert lb.fetch_quotes(["--help"]) == []
    assert cli_called is False


def test_fetch_quotes_handles_nonzero_exit(monkeypatch):
    monkeypatch.setattr(lb.shutil, "which", lambda _name: "/usr/bin/longbridge")
    monkeypatch.setattr(
        lb.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="authentication failed"
        ),
    )
    assert lb.fetch_quotes(["NVDA.US"]) == []


def test_fetch_quotes_handles_timeout(monkeypatch):
    monkeypatch.setattr(lb.shutil, "which", lambda _name: "/usr/bin/longbridge")

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("longbridge", lb.CLI_TIMEOUT_SECONDS)

    monkeypatch.setattr(lb.subprocess, "run", timeout)
    assert lb.fetch_quotes(["NVDA.US"]) == []


def test_fetch_quotes_handles_malformed_json(monkeypatch):
    monkeypatch.setattr(lb.shutil, "which", lambda _name: "/usr/bin/longbridge")
    monkeypatch.setattr(
        lb.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout="not-json", stderr=""
        ),
    )
    assert lb.fetch_quotes(["NVDA.US"]) == []


def test_fetch_quotes_ignores_unrequested_symbols(monkeypatch):
    monkeypatch.setattr(lb.shutil, "which", lambda _name: "/usr/bin/longbridge")
    monkeypatch.setattr(
        lb.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps([SAMPLE_QUOTE, {
                **SAMPLE_QUOTE,
                "symbol": "AAPL.US",
            }]),
            stderr="",
        ),
    )

    result = lb.fetch_quotes(["NVDA.US"])
    assert [item["symbol"] for item in result] == ["NVDA.US"]


def test_normalize_quote_rejects_missing_symbol():
    try:
        lb.normalize_quote({"last": "100"})
    except ValueError as exc:
        assert "symbol" in str(exc)
    else:
        raise AssertionError("Expected missing symbol to be rejected")
