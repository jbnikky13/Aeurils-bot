"""Binance USD-M perpetual universe helpers.

Read-only discovery for AURELIS. No order execution is performed here.
"""
import os
import httpx

BASE = os.getenv("BINANCE_FUTURES_API_URL", "https://fapi.binance.com").rstrip("/")


def all_binance_usdt_perpetual_symbols():
    """Return currently trading Binance USD-M USDT perpetual symbols."""
    r = httpx.get(f"{BASE}/fapi/v1/exchangeInfo", timeout=15)
    r.raise_for_status()
    payload = r.json()
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):
        raise RuntimeError("Binance futures exchangeInfo returned no valid symbols list")
    out = []
    for item in symbols:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "TRADING":
            continue
        if item.get("quoteAsset") != "USDT":
            continue
        if item.get("contractType") != "PERPETUAL":
            continue
        symbol = str(item.get("symbol", "")).upper().strip()
        if symbol:
            out.append(symbol)
    universe = sorted(set(out))
    if not universe:
        raise RuntimeError("Binance futures exchangeInfo returned an empty USDT perpetual universe")
    return universe


def is_valid_binance_usdt_perpetual(symbol, universe=None):
    normalized = str(symbol or "").upper().strip()
    if not normalized:
        return False
    if universe is None:
        universe = all_binance_usdt_perpetual_symbols()
    return normalized in set(universe)
