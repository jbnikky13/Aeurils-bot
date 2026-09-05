"""Dynamic Binance spot USDT universe."""
import os, httpx

BASE=os.getenv("CRYPTO_API_URL","https://data-api.binance.vision").rstrip("/")


def all_binance_usdt_spot_symbols():
    r=httpx.get(f"{BASE}/api/v3/exchangeInfo",timeout=20)
    r.raise_for_status()
    out=[]
    for s in r.json().get("symbols",[]):
        if s.get("status")!="TRADING": continue
        if s.get("quoteAsset")!="USDT": continue
        if s.get("isSpotTradingAllowed") is False: continue
        symbol=s.get("symbol","").upper()
        if not symbol: continue
        # Exclude leveraged-token style products from the spot signal universe.
        if any(symbol.endswith(x) for x in ("UPUSDT","DOWNUSDT","BULLUSDT","BEARUSDT")): continue
        out.append(symbol)
    return sorted(set(out))
