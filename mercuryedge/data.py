from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

from .config import INTERVAL, PERIOD

log = logging.getLogger(__name__)


def load_market(symbol: str) -> pd.DataFrame:
    """Download OHLCV candles and return a clean single-symbol DataFrame."""
    try:
        df = yf.download(
            symbol,
            period=PERIOD,
            interval=INTERVAL,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        log.warning("Data download failed for %s: %s", symbol, exc)
        return pd.DataFrame()

    if df.empty:
        return df

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    wanted = ["Open", "High", "Low", "Close", "Volume"]
    missing = [col for col in wanted if col not in df.columns]
    if missing:
        log.warning("%s missing columns: %s", symbol, missing)
        return pd.DataFrame()

    df = df[wanted].copy()
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df = df[~df.index.duplicated(keep="last")]
    return df
