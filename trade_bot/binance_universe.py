"""Dynamic Binance spot USDT universe with fail-closed production validation."""
import os
import httpx

BASE = os.getenv("CRYPTO_API_URL", "https://data-api.binance.vision").rstrip("/")
LEVERAGED_SUFFIXES = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")


def all_binance_usdt_spot_symbols():
    """Return the current, explicitly tradable Binance USDT spot universe.

    This function is deliberately fail-closed: a failed exchangeInfo request
    raises instead of returning a configured fallback watchlist. Production
    scans must never treat stale/configured symbols as Binance spot symbols.
    """
    r = httpx.get(f"{BASE}/api/v3/exchangeInfo", timeout=20)
    r.raise_for_status()
    payload = r.json()
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):
        raise RuntimeError("Binance exchangeInfo returned no valid symbols list")

    out = []
    for item in symbols:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "TRADING":
            continue
        if item.get("quoteAsset") != "USDT":
            continue
        if item.get("isSpotTradingAllowed") is False:
            continue
        symbol = str(item.get("symbol", "")).upper().strip()
        if not symbol or symbol.endswith(LEVERAGED_SUFFIXES):
            continue
        out.append(symbol)

    universe = sorted(set(out))
    if not universe:
        raise RuntimeError("Binance exchangeInfo returned an empty USDT spot universe")
    return universe


def is_valid_binance_usdt_spot_symbol(symbol, universe=None):
    """Validate a symbol against a known fresh Binance spot universe."""
    normalized = str(symbol or "").upper().strip()
    if not normalized:
        return False
    if universe is None:
        universe = all_binance_usdt_spot_symbols()
    return normalized in set(universe)
