"""Trend + small-cap discovery using CoinGecko market data."""
import os
import httpx
BASE = "https://api.coingecko.com/api/v3"

def _get(path, params=None):
    headers={}
    key=os.getenv("COINGECKO_API_KEY", "").strip()
    if key: headers["x-cg-demo-api-key"]=key
    with httpx.Client(timeout=20) as client:
        r=client.get(BASE+path,params=params or {},headers=headers); r.raise_for_status(); return r.json()

def discover_gems(limit=10):
    trending=_get("/search/trending").get("coins",[])
    markets=_get("/coins/markets",{"vs_currency":"usd","order":"market_cap_desc","per_page":250,"page":1,"sparkline":"false","price_change_percentage":"24h,7d,30d"})
    by_id={x.get("id"):x for x in markets}; out=[]
    for rank,item in enumerate(trending,1):
        cid=item.get("item",{}).get("id"); c=by_id.get(cid)
        if not c: continue
        mcap=c.get("market_cap") or 0; vol=c.get("total_volume") or 0
        if mcap<=0 or vol<1_000_000: continue
        p24=float(c.get("price_change_percentage_24h") or 0); p7=float(c.get("price_change_percentage_7d_in_currency") or c.get("price_change_percentage_7d") or 0)
        score=max(0,min(100,(25-rank*2)+min(30,p24*1.5+15)+min(30,p7+15)+min(15,vol/mcap*100)))
        out.append({"id":cid,"symbol":c.get("symbol",""),"name":c.get("name",""),"market_cap":mcap,"volume_24h":vol,"trend_rank":rank,"score":round(score,1),"price_change_24h":p24,"price_change_7d":p7})
    return sorted(out,key=lambda x:x["score"],reverse=True)[:limit]

def discover_small_caps(limit=10,max_market_cap=1_000_000_000):
    markets=_get("/coins/markets",{"vs_currency":"usd","order":"volume_desc","per_page":250,"page":1,"sparkline":"false","price_change_percentage":"24h,7d,30d"}); out=[]
    for c in markets:
        mcap=c.get("market_cap") or 0; vol=c.get("total_volume") or 0
        if not (10_000_000<=mcap<=max_market_cap and vol>=1_000_000): continue
        p24=float(c.get("price_change_percentage_24h") or 0); p7=float(c.get("price_change_percentage_7d_in_currency") or c.get("price_change_percentage_7d") or 0)
        score=max(0,min(100,50+p24*2+p7+min(30,vol/mcap*100)))
        out.append({"id":c.get("id"),"symbol":c.get("symbol",""),"name":c.get("name",""),"market_cap":mcap,"volume_24h":vol,"score":round(score,1),"price_change_24h":p24,"price_change_7d":p7})
    return sorted(out,key=lambda x:x["score"],reverse=True)[:limit]
