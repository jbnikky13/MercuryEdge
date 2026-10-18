"""Shared Yahoo Finance candles for MercuryEdge and Signal Auditor.

Canonical names deliberately resolve to the same Yahoo ticker used by MercuryEdge's
strategy configuration. This prevents the signal engine and auditor grading a
different instrument. Yahoo data is a research feed, not an executable quote.
"""
from datetime import datetime, timedelta, timezone
import pandas as pd

SYMBOLS = {
    # Match mercuryedge/config.py exactly for inverse/cross FX symbols.
    "EURJPY": "EURJPY=X", "AUDJPY": "AUDJPY=X", "GBPJPY": "GBPJPY=X",
    "EURCHF": "EURCHF=X", "GBPCHF": "GBPCHF=X", "EURGBP": "EURGBP=X",
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "AUDUSD": "AUDUSD=X",
    "NZDUSD": "NZDUSD=X", "USDCAD": "CAD=X", "USDCHF": "CHF=X",
    "USDJPY": "JPY=X", "CADJPY": "CADJPY=X",
    "SPX": "^GSPC", "DJI": "^DJI", "VIX": "^VIX", "DXY": "DX-Y.NYB",
    # MercuryEdge's production config uses ^IXIC (Nasdaq Composite) for NASDAQ.
    # Keep NAS100 as the separate Nasdaq-100 instrument (^NDX).
    "RUSSELL2000": "^RUT", "NASDAQ": "^IXIC",
    "US30": "^DJI", "NAS100": "^NDX", "SPX500": "^GSPC",
    "XAUUSD": "GC=F", "XAGUSD": "SI=F", "NATGAS": "NG=F",
    "UKOIL": "BZ=F", "USOIL": "CL=F", "COPPER": "HG=F",
}
# Reverse lookup also allows MercuryEdge to pass its configured Yahoo ticker.
_TICKER_TO_SYMBOL = {ticker: symbol for symbol, ticker in SYMBOLS.items()}
MAX_AGE_MIN = 15  # A 5-minute candle older than this is not a usable current quote.


def _yf():
    import yfinance as yf
    return yf


def resolve_ticker(symbol_or_ticker):
    value = str(symbol_or_ticker).strip()
    return SYMBOLS.get(value.upper(), value if value in _TICKER_TO_SYMBOL else None)


def _normalize(df):
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    cols = {str(c).lower(): c for c in df.columns}
    if not all(k in cols for k in ("open", "high", "low", "close")):
        return None
    rename = {cols[k]: k.capitalize() for k in ("open", "high", "low", "close")}
    if "volume" in cols:
        rename[cols["volume"]] = "Volume"
    df = df.rename(columns=rename)
    wanted = ["Open", "High", "Low", "Close"] + (["Volume"] if "Volume" in df.columns else [])
    df = df[wanted].copy()
    df.index = pd.to_datetime(df.index, utc=True)
    return df.dropna(subset=["Open", "High", "Low", "Close"])


def get_candles(symbol, start, end=None, interval="5m"):
    """Return UTC-indexed OHLC[V] candles, or None when data is unavailable."""
    ticker = resolve_ticker(symbol)
    if ticker is None:
        return None
    end = end or datetime.now(timezone.utc)
    try:
        raw = _yf().download(
            ticker, start=start, end=end, interval=interval,
            progress=False, auto_adjust=False, threads=False,
        )
    except Exception:
        return None
    return _normalize(raw)


def get_history(symbol_or_ticker, period="6mo", interval="1h"):
    """Download a rolling period using the same resolved ticker and normalizer."""
    ticker = resolve_ticker(symbol_or_ticker)
    if ticker is None:
        return None
    try:
        raw = _yf().download(
            ticker, period=period, interval=interval,
            progress=False, auto_adjust=False, threads=False,
        )
    except Exception:
        return None
    return _normalize(raw)


def get_live_quote(symbol):
    """Return a fresh 5-minute close with its UTC timestamp, or None.

    Yahoo candles are a sanity-check feed, not executable broker quotes.
    """
    now = datetime.now(timezone.utc)
    df = get_candles(symbol, now - timedelta(hours=6), now, interval="5m")
    if df is None or df.empty:
        return None
    stamp = df.index[-1]
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    age_min = (now - stamp.to_pydatetime()).total_seconds() / 60
    if age_min < -2 or age_min > MAX_AGE_MIN:
        return None
    price = float(df["Close"].iloc[-1])
    if not pd.notna(price) or price <= 0:
        return None
    return {"price": price, "timestamp": stamp.isoformat(), "age_minutes": max(0.0, age_min)}


def get_live_price(symbol):
    """Backward-compatible price-only wrapper; rejects stale quotes."""
    quote = get_live_quote(symbol)
    return quote["price"] if quote else None


def feed_agrees(symbol, entry, live=None, atr=None):
    """Compare entry to the latest quote using ATR-scaled tolerance, not a fixed 2%."""
    live = get_live_price(symbol) if live is None else live
    try:
        price = float(live)
        entry = float(entry)
        atr_value = float(atr)
        if not all(pd.notna(v) for v in (price, entry, atr_value)) or min(price, entry, atr_value) <= 0:
            return False
        return abs(price - entry) <= 0.35 * atr_value
    except (TypeError, ValueError, ZeroDivisionError):
        return False


def health_check(symbols=None):
    bad = []
    for symbol in symbols or SYMBOLS:
        price = get_live_price(symbol)
        print(f"{symbol:12s} {'OK ' + format(price, '.5g') if price is not None else 'NO DATA'}")
        if price is None:
            bad.append(symbol)
    return bad


if __name__ == "__main__":
    health_check()
