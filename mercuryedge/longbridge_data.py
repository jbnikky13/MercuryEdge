"""Optional Longbridge quote enrichment through the authenticated CLI.

This adapter invokes `longbridge quote` and parses its JSON output. It never
reads CLI credential files or imports trading APIs. Existing FX and commodity
candle providers remain unchanged.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

CLI_TIMEOUT_SECONDS = 20


def configured_symbols() -> list[str]:
    """Read and deduplicate configured Longbridge symbols."""
    raw = os.getenv("MERCURY_LONGBRIDGE_SYMBOLS", "")
    return list(dict.fromkeys(
        item.strip().upper() for item in raw.split(",") if item.strip()
    ))


def _observation_time(observed_at: datetime | None = None) -> str:
    observed = observed_at or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    else:
        observed = observed.astimezone(timezone.utc)
    return observed.isoformat()


def _extended_session(data: Any) -> dict[str, Any] | None:
    """Keep only documented extended-session quote fields."""
    if not isinstance(data, dict):
        return None

    allowed = (
        "last", "timestamp", "high", "low",
        "volume", "turnover", "prev_close",
    )
    result = {key: data[key] for key in allowed if key in data}
    return result or None


def normalize_quote(
    quote: dict[str, Any],
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Normalize CLI JSON while retaining extended-session timestamps."""
    if not isinstance(quote, dict):
        raise ValueError("Quote must be a JSON object")

    symbol = str(quote.get("symbol") or "").strip().upper()
    if not symbol:
        raise ValueError("Quote is missing its symbol")

    result = {
        "symbol": symbol,
        "last": quote.get("last"),
        "previous_close": quote.get("prev_close"),
        "open": quote.get("open"),
        "high": quote.get("high"),
        "low": quote.get("low"),
        "volume": quote.get("volume"),
        "turnover": quote.get("turnover"),
        "trade_session": "",
        "trade_status": str(quote.get("status") or ""),
        "observed_at_utc": _observation_time(observed_at),
        "timestamp_type": (
            "MercuryEdge observation time; not exchange event time"
        ),
        "source": "Longbridge CLI",
    }

    for session in ("pre_market", "post_market", "overnight"):
        normalized = _extended_session(quote.get(session))
        if normalized is not None:
            result[session] = normalized

    return result


def _parse_cli_output(stdout: str) -> list[dict[str, Any]]:
    """Parse the CLI's JSON array and reject malformed responses."""
    try:
        payload = json.loads(stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Longbridge CLI returned invalid JSON") from exc

    if not isinstance(payload, list):
        raise ValueError("Longbridge CLI JSON response must be an array")

    return [normalize_quote(item) for item in payload]


def fetch_quotes(symbols: list[str] | None = None) -> list[dict[str, Any]]:
    """Fetch optional quotes; provider failures never interrupt the main scan."""
    requested = symbols if symbols is not None else configured_symbols()
    requested = list(dict.fromkeys(
        str(symbol).strip().upper()
        for symbol in requested
        if str(symbol).strip()
    ))

    if not requested:
        return []

    # Prevent malformed symbols from being interpreted as CLI options.
    if any(symbol.startswith("-") for symbol in requested):
        log.warning(
            "Longbridge quote request contains an invalid option-like symbol; "
            "continuing without supplemental quotes."
        )
        return []

    executable = shutil.which("longbridge")
    if not executable:
        log.warning(
            "Longbridge symbols configured but the Longbridge CLI is not installed; "
            "continuing without supplemental quotes."
        )
        return []

    command = [executable, "quote", *requested, "--format", "json"]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT_SECONDS,
            check=False,
        )

        if completed.returncode != 0:
            log.warning(
                "Longbridge CLI quote request failed with exit code %s; "
                "continuing without supplemental quotes.",
                completed.returncode,
            )
            return []

        quotes = _parse_cli_output(completed.stdout)

        requested_set = set(requested)
        unexpected = [
            quote["symbol"] for quote in quotes
            if quote["symbol"] not in requested_set
        ]
        if unexpected:
            log.warning(
                "Longbridge CLI returned unrequested symbols; ignoring them."
            )
            quotes = [
                quote for quote in quotes
                if quote["symbol"] in requested_set
            ]

        return quotes

    except subprocess.TimeoutExpired:
        log.warning(
            "Longbridge CLI quote request timed out; "
            "continuing without supplemental quotes."
        )
    except (OSError, ValueError, TypeError) as exc:
        log.warning(
            "Longbridge CLI quote response failed (%s); "
            "continuing without supplemental quotes.",
            type(exc).__name__,
        )
    except Exception as exc:
        log.warning(
            "Unexpected Longbridge CLI failure (%s); "
            "continuing without supplemental quotes.",
            type(exc).__name__,
        )

    return []


def main() -> int:
    symbols = configured_symbols()
    if not symbols:
        print(
            "Longbridge supplemental quotes disabled: "
            "MERCURY_LONGBRIDGE_SYMBOLS is empty."
        )
        return 0

    quotes = fetch_quotes(symbols)
    print(json.dumps(
        {"requested": symbols, "returned": quotes},
        indent=2,
        default=str,
    ))
    return 0 if quotes else 1


if __name__ == "__main__":
    raise SystemExit(main())
