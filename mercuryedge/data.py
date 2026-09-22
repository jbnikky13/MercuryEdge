from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

from .config import HISTORICAL_INTERVAL, HISTORICAL_PERIOD, INTERVAL, PERIOD

log = logging.getLogger(__name__)


def load_market(symbol: str) -> pd.DataFrame:
    return _download(symbol, PERIOD, INTERVAL)


def load_historical(symbol: str) -> pd.DataFrame:
    """Load a longer, lower-frequency history used for pattern research."""
    return _download(symbol, HISTORICAL_PERIOD, HISTORICAL_INTERVAL)


def load_market_window(symbol: str, start: str | None = None) -> pd.DataFrame:
    """Load candles around a published signal for outcome resolution."""
    if start:
        try:
            start_ts = pd.Timestamp(start)
            end = (start_ts + pd.Timedelta(days=14)).isoformat()
            df = yf.download(
                symbol,
                start=start_ts.isoformat(),
                end=end,
                interval=INTERVAL,
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            return _normalize(df, symbol)
        except Exception as exc:
            log.warning("Window download failed for %s: %s", symbol, exc)
    return load_market(symbol)


def _normalize(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    wanted = ["Open", "High", "Low", "Close", "Volume"]
    missing = [col for col in wanted if col not in df.columns]
    if missing:
        log.warning("%s missing columns: %s", symbol, missing)
        return pd.DataFrame()
    return df[wanted].copy().dropna(subset=["Open", "High", "Low", "Close"])


def _download(symbol: str, period: str, interval: str) -> pd.DataFrame:
    try:
        df = yf.download(
            symbol,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        log.warning("Data download failed for %s: %s", symbol, exc)
        return pd.DataFrame()

    df = _normalize(df, symbol)
    if df.empty:
        return df

    df = df[~df.index.duplicated(keep="last")]
    return df
