"""Promote only analyzable discovered crypto candidates into the daily gate."""
import os
from .gem_finder import discover_gems, discover_small_caps
from .market_data import crypto_klines
from .live_setup import _contract_for

async def discovered_symbols(base_symbols):
    trending=discover_gems(limit=int(os.getenv('GEM_DISCOVERY_LIMIT','5')))
    small=discover_small_caps(limit=int(os.getenv('SMALL_CAP_DISCOVERY_LIMIT','5')),max_market_cap=int(os.getenv('SMALL_CAP_MAX_MARKET_CAP','1000000000')))
    seen=set(x.upper() for x in base_symbols); out=[]; rejected=[]
    for item in [*trending,*small]:
        raw=str(item.get('symbol') or '').upper().strip()
        if not raw: continue
        symbol=raw if raw.endswith('USDT') else raw+'USDT'
        if symbol in seen: continue
        seen.add(symbol)
        try:
            # Discovery is allowed to suggest anything, but only assets with usable
            # OHLC data and a configured token contract can enter the actionable path.
            crypto_klines(symbol)
            _contract_for(symbol)
            out.append(symbol)
        except Exception as exc:
            rejected.append({'symbol':symbol,'reason':str(exc)})
    return out,trending,small,rejected
