"""Reconcile Binance Demo positions into a local execution journal."""
from __future__ import annotations
import json
from .binance_demo import BinanceDemoClient
from .execution_config import assert_demo_only


def snapshot(symbol=None):
    cfg=assert_demo_only()
    if cfg["mode"]!="BINANCE_DEMO":
        raise RuntimeError("Demo reconciliation requires BINANCE_DEMO mode.")
    client=BinanceDemoClient()
    return {
        "mode":"BINANCE_DEMO",
        "account":client.account(),
        "positions":client.position_risk(symbol),
    }


if __name__=="__main__":
    print(json.dumps(snapshot(),indent=2))
