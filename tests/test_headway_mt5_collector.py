from types import SimpleNamespace
from datetime import date
from pathlib import Path

import pytest

from research.headway_mt5_collector import (
    EXPECTED_SERVER,
    FeedError,
    collect,
    resolve_symbol,
    session_bounds,
)


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    COPY_TICKS_ALL = 0
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_H1 = 60
    TIMEFRAME_H4 = 240

    def __init__(self, server="Headway-Demo", trade_mode=0, symbols=None):
        self.server = server
        self.trade_mode = trade_mode
        self.symbols = symbols or ["EURUSD", "XAGUSD.m", "XAGUSDpro"]
        self.closed = False

    def initialize(self):
        return True

    def shutdown(self):
        self.closed = True

    def terminal_info(self):
        return SimpleNamespace(connected=True, build=5000)

    def account_info(self):
        return SimpleNamespace(server=self.server, trade_mode=self.trade_mode)

    def symbols_get(self):
        return [SimpleNamespace(name=name) for name in self.symbols]

    def last_error(self):
        return (0, "ok")


def test_session_bounds_use_lagos_midnight():
    start, end = session_bounds(date(2026, 10, 30))
    assert (end - start).total_seconds() == 86400
    assert start.hour == 23


def test_exact_symbol_match_wins():
    mt5 = FakeMT5()
    assert resolve_symbol(mt5, "EURUSD") == ("EURUSD", "exact")


def test_unique_suffix_is_allowed():
    mt5 = FakeMT5(symbols=["XAGUSD.m"])
    assert resolve_symbol(mt5, "XAGUSD") == ("XAGUSD.m", "unique_suffix")


def test_ambiguous_suffix_is_rejected():
    mt5 = FakeMT5()
    assert resolve_symbol(mt5, "XAGUSD") == (None, "ambiguous:XAGUSD.m,XAGUSDpro")


def test_wrong_server_is_rejected_and_terminal_closed(tmp_path):
    mt5 = FakeMT5(server="Headway-Real")
    with pytest.raises(FeedError, match="Wrong MT5 server"):
        collect(date(2026, 10, 30), ["EURUSD"], Path(tmp_path), mt5=mt5)
    assert mt5.closed


def test_non_demo_account_is_rejected_and_terminal_closed(tmp_path):
    mt5 = FakeMT5(trade_mode=1)
    with pytest.raises(FeedError, match="not marked DEMO"):
        collect(date(2026, 10, 30), ["EURUSD"], Path(tmp_path), mt5=mt5)
    assert mt5.closed


def test_expected_server_label_is_headway_demo():
    assert EXPECTED_SERVER == "headway-demo"
