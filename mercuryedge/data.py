from __future__ import annotations

import logging
import pandas as pd

from .config import HISTORICAL_INTERVAL, HISTORICAL_PERIOD, INTERVAL, PERIOD
from market_data import get_candles, get_history

log = logging.getLogger(__name__)


def load_market(symbol: str) -> pd.DataFrame:
    return _download(symbol, PERIOD, INTERVAL)


def load_historical(symbol: str) -> pd.DataFrame:
    """Load longer, lower-frequency history using the shared ticker provider."""
    return _download(symbol, HISTORICAL_PERIOD, HISTORICAL_INTERVAL)


def load_market_window(symbol: str, start: str | None = None) -> pd.DataFrame:
    """Load candles around a published signal from the same shared source."""
    if start:
        try:
            start_ts = pd.Timestamp(start)
            if start_ts.tzinfo is None:
                start_ts = start_ts.tz_localize("UTC")
            else:
                start_ts = start_ts.tz_convert("UTC")
            end_ts = start_ts + pd.Timedelta(days=14)
            df = get_candles(symbol, start_ts.to_pydatetime(), end_ts.to_pydatetime(), interval=INTERVAL)
            return _normalize(df, symbol)
        except Exception as exc:
            log.warning("Window download failed for %s: %s", symbol, exc)
    return load_market(symbol)


def _normalize(df: pd.DataFrame | None, symbol: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    # Shared market_data returns title-case OHLC[V] columns and a UTC index.
    wanted = ["Open", "High", "Low", "Close"]
    if "Volume" not in out.columns:
        out["Volume"] = 0.0
    missing = [col for col in wanted if col not in out.columns]
    if missing:
        log.warning("%s missing columns: %s", symbol, missing)
        return pd.DataFrame()
    out = out[wanted + ["Volume"]].copy()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.dropna(subset=wanted)


def _download(symbol: str, period: str, interval: str) -> pd.DataFrame:
    try:
        df = get_history(symbol, period=period, interval=interval)
    except Exception as exc:
        log.warning("Shared data download failed for %s: %s", symbol, exc)
        return pd.DataFrame()
    return _normalize(df, symbol)
