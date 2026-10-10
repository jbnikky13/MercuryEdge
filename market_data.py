"""Shared Yahoo Finance price/candle source for MercuryEdge and Signal Auditor."""
from datetime import datetime, timedelta, timezone
import pandas as pd

SYMBOLS = {
    "EURJPY":"EURJPY=X","AUDJPY":"AUDJPY=X","GBPJPY":"GBPJPY=X","EURCHF":"EURCHF=X","GBPCHF":"GBPCHF=X","EURGBP":"EURGBP=X",
    "EURUSD":"EURUSD=X","GBPUSD":"GBPUSD=X","AUDUSD":"AUDUSD=X","NZDUSD":"NZDUSD=X","USDCAD":"USDCAD=X","USDCHF":"USDCHF=X",
    "USDJPY":"JPY=X","CADJPY":"CADJPY=X","SPX":"^GSPC","DJI":"^DJI","VIX":"^VIX","DXY":"DX-Y.NYB",
    "RUSSELL2000":"^RUT","NASDAQ":"^NDX","US30":"^DJI","NAS100":"^NDX","SPX500":"^GSPC",
    "XAUUSD":"GC=F","XAGUSD":"SI=F","NATGAS":"NG=F","UKOIL":"BZ=F","USOIL":"CL=F","COPPER":"HG=F",
}
MAX_AGE_MIN = 90
MAX_ENTRY_DEVIATION = 0.02

def _yf():
    import yfinance as yf
    return yf

def get_candles(symbol, start, end=None, interval="5m"):
    ticker = SYMBOLS.get(str(symbol).upper())
    if ticker is None:
        return None
    end = end or datetime.now(timezone.utc)
    try:
        df = _yf().download(ticker, start=start, end=end, interval=interval, progress=False, auto_adjust=False, threads=False)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    cols = {str(c).lower(): c for c in df.columns}
    if not all(k in cols for k in ("open","high","low","close")):
        return None
    df = df.rename(columns={cols[k]: k for k in ("open","high","low","close")})[["open","high","low","close"]]
    df.index = pd.to_datetime(df.index, utc=True)
    return df.dropna()

def get_live_price(symbol):
    now = datetime.now(timezone.utc)
    df = get_candles(symbol, now-timedelta(hours=6), now, interval="5m")
    if df is None or df.empty or (now-df.index[-1]).total_seconds()/60 > MAX_AGE_MIN:
        return None
    return float(df["close"].iloc[-1])

def feed_agrees(symbol, entry, live=None):
    live = get_live_price(symbol) if live is None else live
    return live is not None and abs(live-entry)/live <= MAX_ENTRY_DEVIATION

def health_check(symbols=None):
    bad=[]
    for symbol in symbols or SYMBOLS:
        price=get_live_price(symbol)
        print(f"{symbol:12s} {'OK '+format(price,'.5g') if price else 'NO DATA'}")
        if price is None: bad.append(symbol)
    return bad

if __name__ == "__main__":
    health_check()
