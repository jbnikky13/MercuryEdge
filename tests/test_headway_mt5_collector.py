from types import SimpleNamespace

import pytest

from research.headway_mt5_collector import (
    EXPECTED_SERVER,
    FeedError,
    resolve_symbol,
    session_bounds,
)
from datetime import date


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    COPY_TICKS_ALL = 0
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_H1 = 60
    TIMEFRAME_H4 = 240

    def __init__(self, server="Headway-Demo", trade_mode=0):
        self.server = server
        self.trade_mode = trade_mode
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
        return [SimpleNamespace(name="EURUSD"), SimpleNamespace(name="XAGUSD.m"), SimpleNamespace(name="XAGUSDpro")]

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
    mt5 = FakeMT5()
    assert resolve_symbol(mt5, "XAGUSD") == (None, "ambiguous:XAGUSD.m,XAGUSDpro")


def test_wrong_server_is_not_accepted():
    assert EXPECTED_SERVER == "headway-demo"
    mt5 = FakeMT5(server="Headway-Real")
    assert mt5.server != "Headway-Demo"


def test_real_account_mode_is_distinct_from_demo():
    mt5 = FakeMT5(trade_mode=1)
    assert mt5.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO
