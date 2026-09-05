"""Live confluence evidence providers.
Uses public market/DEX endpoints where possible. Missing evidence is UNKNOWN, never PASS.
Optional on-chain enrichment is supported through DEXScreener data; wallet-level signals require a configured provider and are never fabricated.
"""
import httpx

async def crypto_evidence(symbol):
    base=symbol.upper().replace('/','')
    pair=base[:-4]+'/'+'USDT' if base.endswith('USDT') else base
    evidence={}
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            r=await c.get('https://api.dexscreener.com/latest/dex/search',params={'q':pair})
            data=r.json(); pairs=data.get('pairs') or []
        if pairs:
            p=max(pairs,key=lambda x:float((x.get('liquidity') or {}).get('usd') or 0))
            liq=float((p.get('liquidity') or {}).get('usd') or 0)
            vol=float((p.get('volume') or {}).get('h24') or 0)
            tx=p.get('txns') or {}; h24=(tx.get('h24') or {})
            buys=int(h24.get('buys') or 0); sells=int(h24.get('sells') or 0)
            evidence['volume_liquidity']=liq>100000 and vol>liq
            evidence['onchain_dex_activity']=(buys+sells)>=50
            evidence['buy_sell_pressure']=buys>sells
            evidence['liquidity_depth']=liq>=250000
    except Exception:
        pass
    return evidence

def stock_evidence(signal):
    # The signal object supplies price/technical context; no external stock confirmation is invented here.
    return {}
