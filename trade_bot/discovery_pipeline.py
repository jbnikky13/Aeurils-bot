"""Promote discovered crypto candidates into the same daily signal gate."""
import os
from .gem_finder import discover_gems, discover_small_caps

async def discovered_symbols(base_symbols):
    trending=discover_gems(limit=int(os.getenv('GEM_DISCOVERY_LIMIT','5')))
    small=discover_small_caps(limit=int(os.getenv('SMALL_CAP_DISCOVERY_LIMIT','5')),max_market_cap=int(os.getenv('SMALL_CAP_MAX_MARKET_CAP','1000000000')))
    seen=set(x.upper() for x in base_symbols); out=[]
    for item in [*trending,*small]:
        raw=str(item.get('symbol') or '').upper().strip()
        if not raw: continue
        symbol=raw if raw.endswith('USDT') else raw+'USDT'
        if symbol not in seen:
            seen.add(symbol); out.append(symbol)
    return out,trending,small
