from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Market:
    symbol: str
    name: str
    category: str


MARKETS = [
    Market("EURUSD=X", "EURUSD", "forex"),
    Market("GBPUSD=X", "GBPUSD", "forex"),
    Market("JPY=X", "USDJPY", "forex"),
    Market("CHF=X", "USDCHF", "forex"),
    Market("AUDUSD=X", "AUDUSD", "forex"),
    Market("NZDUSD=X", "NZDUSD", "forex"),
    Market("CAD=X", "USDCAD", "forex"),
    Market("EURGBP=X", "EURGBP", "forex"),
    Market("EURJPY=X", "EURJPY", "forex"),
    Market("GBPJPY=X", "GBPJPY", "forex"),
    Market("AUDJPY=X", "AUDJPY", "forex"),
    Market("CADJPY=X", "CADJPY", "forex"),
    Market("EURCHF=X", "EURCHF", "forex"),
    Market("GBPCHF=X", "GBPCHF", "forex"),
    Market("GC=F", "XAUUSD", "commodity"),
    Market("SI=F", "XAGUSD", "commodity"),
    Market("CL=F", "USOIL", "commodity"),
    Market("BZ=F", "UKOIL", "commodity"),
    Market("NG=F", "NATGAS", "commodity"),
    Market("HG=F", "COPPER", "commodity"),
]

# Intraday data powers the actual setup. A separate long daily history powers
# historical-pattern research so short signal windows do not define the model.
PERIOD = os.getenv("MERCURY_PERIOD", "6mo")
INTERVAL = os.getenv("MERCURY_INTERVAL", "1h")
HISTORICAL_PERIOD = os.getenv("MERCURY_HISTORICAL_PERIOD", "10y")
HISTORICAL_INTERVAL = os.getenv("MERCURY_HISTORICAL_INTERVAL", "1d")
MAX_SETUPS = int(os.getenv("MERCURY_MAX_SETUPS", "5"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
