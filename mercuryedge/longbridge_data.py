"""Optional Longbridge quote enrichment for supported securities.

This module is deliberately separate from market_data.py: the existing Yahoo
candles for FX, commodities, and indices remain untouched. Longbridge is used
only through QuoteContext; no trading context or order API is imported.

OAuth is loaded only from an existing local SDK token cache. This prevents a
headless GitHub Actions job from unexpectedly starting an interactive login.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def configured_symbols() -> list[str]:
    """Read a comma-separated list of Longbridge-supported security symbols."""
    raw = os.getenv("MERCURY_LONGBRIDGE_SYMBOLS", "")
    return list(dict.fromkeys(
        item.strip().upper() for item in raw.split(",") if item.strip()
    ))


def _field(obj: Any, name: str, default: Any = None) -> Any:
    value = getattr(obj, name, default)
    if value is None:
        return default
    # SDK decimal wrappers may expose a normal string representation.
    return str(value) if name in {"last_done", "prev_close_price", "open", "high", "low", "turnover"} else value


def normalize_quote(quote: Any, observed_at: datetime | None = None) -> dict[str, Any]:
    """Normalize a Longbridge SecurityQuote without inventing exchange timestamps."""
    observed = observed_at or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    else:
        observed = observed.astimezone(timezone.utc)
    return {
        "symbol": str(_field(quote, "symbol", "")),
        "last": _field(quote, "last_done"),
        "previous_close": _field(quote, "prev_close_price"),
        "open": _field(quote, "open"),
        "high": _field(quote, "high"),
        "low": _field(quote, "low"),
        "volume": _field(quote, "volume"),
        "turnover": _field(quote, "turnover"),
        "trade_session": str(_field(quote, "trade_session", "")),
        "trade_status": str(_field(quote, "trade_status", "")),
        "observed_at_utc": observed.isoformat(),
        "timestamp_type": "MercuryEdge observation time; not exchange event time",
        "source": "Longbridge OpenAPI",
    }


def _oauth_config(client_id: str):
    """Load an already-authorized OAuth cache; never launch an interactive flow."""
    token_path = Path.home() / ".longbridge" / "openapi" / "tokens" / client_id
    if not token_path.is_file() or token_path.stat().st_size == 0:
        raise RuntimeError(
            "Longbridge OAuth token cache is missing. Authenticate this runtime "
            "with the official Longbridge CLI before enabling quote enrichment."
        )
    from longbridge.openapi import Config, OAuthBuilder

    oauth = OAuthBuilder(client_id).build(lambda _url: None)
    return Config.from_oauth(oauth)


def fetch_quotes(symbols: list[str] | None = None) -> list[dict[str, Any]]:
    """Fetch optional quote context. Returns [] on missing config or provider failure."""
    requested = symbols if symbols is not None else configured_symbols()
    requested = list(dict.fromkeys(
        str(symbol).strip().upper() for symbol in requested if str(symbol).strip()
    ))
    if not requested:
        return []

    client_id = os.getenv("LONGBRIDGE_OAUTH_CLIENT_ID", "").strip()
    if not client_id:
        log.warning(
            "Longbridge symbols configured but LONGBRIDGE_OAUTH_CLIENT_ID is unset; "
            "continuing without supplemental quotes."
        )
        return []

    try:
        from longbridge.openapi import QuoteContext

        config = _oauth_config(client_id)
        context = QuoteContext(config)
        quotes = context.quote(requested)
        return [normalize_quote(item) for item in quotes]
    except Exception as exc:
        log.warning(
            "Longbridge supplemental quote request failed (%s); "
            "existing FX/commodity data pipeline is unchanged.",
            type(exc).__name__,
        )
        return []


def main() -> int:
    import json

    symbols = configured_symbols()
    if not symbols:
        print("Longbridge supplemental quotes disabled: MERCURY_LONGBRIDGE_SYMBOLS is empty.")
        return 0
    quotes = fetch_quotes(symbols)
    print(json.dumps({"requested": symbols, "returned": quotes}, indent=2, default=str))
    return 0 if quotes else 1


if __name__ == "__main__":
    raise SystemExit(main())
