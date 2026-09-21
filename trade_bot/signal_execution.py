"""Execution policy for the AURELIS scheduled signal pipeline.

The signal generator remains authoritative. When DEMO execution is enabled,
each qualifying signal is immediately mirrored to Binance Futures Demo.
PAPER remains the default.
"""
from __future__ import annotations
import os
from .demo_bridge import execute_signal


def demo_execution_enabled() -> bool:
    return os.getenv("EXECUTION_MODE", "PAPER").upper() == "BINANCE_DEMO"


def execute_signal_if_enabled(signal: dict, equity: float):
    if not demo_execution_enabled():
        return {"executed": False, "mode": "PAPER", "reason": "demo execution disabled"}
    result = execute_signal(signal, equity)
    return {"executed": True, **result}
