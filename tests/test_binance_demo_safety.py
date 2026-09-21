import os
import pytest

from trade_bot.binance_demo import BinanceDemoClient, DemoTradingDisabled
from trade_bot.execution_config import assert_demo_only


def test_paper_is_safe_default(monkeypatch):
    monkeypatch.delenv("EXECUTION_MODE", raising=False)
    assert_demo_only()
    with pytest.raises(DemoTradingDisabled):
        BinanceDemoClient()


def test_live_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE","LIVE")
    with pytest.raises(RuntimeError):
        assert_demo_only()


def test_demo_requires_demo_credentials(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE","BINANCE_DEMO")
    monkeypatch.delenv("BINANCE_DEMO_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_DEMO_API_SECRET", raising=False)
    with pytest.raises(DemoTradingDisabled):
        BinanceDemoClient()
