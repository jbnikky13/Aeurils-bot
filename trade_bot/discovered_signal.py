"""Signal generation for discovered assets that are not listed on Binance.
Uses CoinGecko candles + CoinGecko token metadata + DEXScreener evidence.
No wallet-level confirmation is fabricated.
"""
import os
import httpx
import pandas as pd
from .indicators import score as technical_score, enrich
from .signal_engine import build_setup
from .market_regime import classify_regime
from .gemini_signal import confirm

CG="https://api.coingecko.com/api/v3"

def _headers():
    key=os.getenv("COINGECKO_API_KEY","").strip()
    return {"x-cg-demo-api-key":key} if key else {}

async def _cg(path,params=None):
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.get(CG+path,params=params or {},headers=_headers()); r.raise_for_status(); return r.json()

async def resolve_asset(symbol):
    sym=symbol.upper().replace("USDT","")
    explicit=os.getenv("COINGECKO_ID_MAP","")
    for item in explicit.split(","):
        if ":" in item:
            a,b=item.split(":",1)
            if a.strip().upper()==sym: return b.strip()
    data=await _cg("/search",{"query":sym})
    coins=data.get("coins") or []
    exact=[x for x in coins if str(x.get("symbol","")).upper()==sym]
    return (exact[0] if exact else coins[0]).get("id") if (exact or coins) else None

async def discovered_setup(symbol):
    coin_id=await resolve_asset(symbol)
    if not coin_id: raise RuntimeError(f"Unable to resolve CoinGecko asset for {symbol}")
    meta=await _cg(f"/coins/{coin_id}",{"localization":"false","tickers":"false","market_data":"false","community_data":"false","developer_data":"false","sparkline":"false"})
    chain=next((k for k,v in (meta.get("platforms") or {}).items() if v),None)
    contract=(meta.get("platforms") or {}).get(chain) if chain else None
    market=await _cg(f"/coins/{coin_id}/market_chart",{"vs_currency":"usd","days":"365","interval":"daily"})
    prices=market.get("prices") or []; volumes=market.get("total_volumes") or []
    if len(prices)<80: raise RuntimeError(f"Insufficient CoinGecko candle history for {symbol}")
    vol={int(t):v for t,v in volumes}; rows=[]
    for t,p in prices:
        rows.append({"open_time":int(t),"open":p,"high":p,"low":p,"close":p,"volume":vol.get(int(t),0)})
    df=pd.DataFrame(rows)
    tech,tbias,atr,reasons=technical_score(df)
    r=enrich(df).iloc[-1]; regime=classify_regime({"close":r.close,"ema20":r.ema20,"ema50":r.ema50,"ema200":r.ema200,"atr":r.atr})
    evidence={"token_contract":contract,"chain":chain}
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            q=symbol.upper().replace("USDT","")+"/USDT"
            res=await c.get("https://api.dexscreener.com/latest/dex/search",params={"q":q})
            pairs=(res.json().get("pairs") or [])
        if pairs:
            p=max(pairs,key=lambda x:float((x.get("liquidity") or {}).get("usd") or 0))
            liq=float((p.get("liquidity") or {}).get("usd") or 0); vol24=float((p.get("volume") or {}).get("h24") or 0)
            tx=p.get("txns") or {}; h=h24=tx.get("h24") or {}; buys=int(h.get("buys") or 0); sells=int(h.get("sells") or 0)
            evidence.update({"volume_liquidity":liq>100000 and vol24>liq,"onchain_dex_activity":buys+sells>=50,"buy_sell_pressure":buys>sells,"liquidity_depth":liq>=250000,"dex_liquidity_usd":liq})
    except Exception: pass
    onchain_score=50+10*sum(bool(evidence.get(k)) for k in ("onchain_dex_activity","buy_sell_pressure","liquidity_depth","volume_liquidity"))
    onchain_score=min(100,onchain_score)
    setup=build_setup(symbol.upper(),"crypto",float(df.iloc[-1].close),tech,onchain_score,50,tbias,0.5 if evidence.get("buy_sell_pressure") else -0.5 if evidence.get("onchain_dex_activity") and not evidence.get("buy_sell_pressure") else 0.0,float(atr or 0),regime)
    ai=confirm(symbol.upper(),tech,tbias,onchain_score,setup.whale_bias or 0,float(df.iloc[-1].close),float(atr or 0))
    setup.gemini_confidence=float(ai.get("confidence",0)); setup.gemini_decision=ai.get("decision"); setup.gemini_rationale=ai.get("rationale","")
    if ai.get("decision")!=setup.direction or setup.gemini_confidence<float(os.getenv("GEMINI_MIN_CONFIDENCE","70")):
        setup.direction="WAIT"; setup.entry_low=setup.entry_high=setup.stop_loss=setup.take_profit_1=setup.take_profit_2=setup.risk_reward=None
        setup.invalidation="Gemini confirmation did not meet the configured confidence/consensus gate."
    setup.reasons=reasons+[f"Market regime: {regime}",f"CoinGecko asset: {coin_id}",f"Token contract: {contract or 'UNKNOWN'}",f"DEX evidence: {sum(bool(evidence.get(k)) for k in ('onchain_dex_activity','buy_sell_pressure','liquidity_depth','volume_liquidity'))}/4",f"Gemini confirmation: {ai.get('decision')} ({setup.gemini_confidence:.0f}/100)",ai.get("rationale","")]
    setup.discovery_evidence=evidence
    return setup
