"""Resolve discovered assets without assuming Binance symbols/contracts."""
import os
import httpx
from .gem_finder import discover_gems, discover_small_caps

CG_BASE="https://api.coingecko.com/api/v3"

def _cg_get(path,params=None):
    headers={}; key=os.getenv("COINGECKO_API_KEY","").strip()
    if key: headers["x-cg-demo-api-key"]=key
    with httpx.Client(timeout=20) as c:
        r=c.get(CG_BASE+path,params=params or {},headers=headers); r.raise_for_status(); return r.json()

def _markets_for(ids):
    if not ids:return {}
    data=_cg_get("/coins/markets",{"vs_currency":"usd","ids":",".join(ids),"per_page":250,"page":1,"sparkline":"false"})
    return {x.get("id"):x for x in data}

def _contract_for_coin(coin_id):
    d=_cg_get(f"/coins/{coin_id}",{"localization":"false","tickers":"false","market_data":"false","community_data":"false","developer_data":"false","sparkline":"false"})
    platforms=d.get("platforms") or {}
    for platform,address in platforms.items():
        if address:
            return platform,address
    return "native",None

def _coin_id_map(items):
    return {str(x.get('symbol','')).upper():str(x.get('id','')) for x in items if x.get('symbol') and x.get('id')}

async def discovered_symbols(base_symbols):
    trending=discover_gems(limit=int(os.getenv('GEM_DISCOVERY_LIMIT','5')))
    small=discover_small_caps(limit=int(os.getenv('SMALL_CAP_DISCOVERY_LIMIT','5')),max_market_cap=int(os.getenv('SMALL_CAP_MAX_MARKET_CAP','1000000000')))
    seen=set(x.upper() for x in base_symbols); candidates=[]
    for item in [*trending,*small]:
        raw=str(item.get('symbol') or '').upper().strip(); cid=str(item.get('id') or '').strip()
        if not raw or not cid: continue
        symbol=raw+'USDT' if not raw.endswith('USDT') else raw
        if symbol in seen: continue
        seen.add(symbol); candidates.append((symbol,cid))
    rejected=[]; out=[]
    try: markets=_markets_for([cid for _,cid in candidates])
    except Exception as exc: return [],trending,small,[{'symbol':'DISCOVERY','reason':f'CoinGecko market lookup failed: {exc}'}]
    for symbol,cid in candidates:
        try:
            market=markets.get(cid)
            if not market: raise RuntimeError(f"CoinGecko market data unavailable for {cid}")
            platform,address=_contract_for_coin(cid)
            out.append({'symbol':symbol,'coin_id':cid,'platform':platform,'contract':address,'market':market})
        except Exception as exc: rejected.append({'symbol':symbol,'reason':str(exc)})
    return out,trending,small,rejected
