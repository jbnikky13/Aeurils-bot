import os
from .market_data import crypto_klines, stock_daily
from .indicators import score as technical_score, enrich
from .signal_engine import build_setup
from .stock_sentiment import score as stock_sentiment
from .gemini_signal import confirm
from .market_regime import classify_regime

def _regime(df):
    r=enrich(df).iloc[-1]
    return classify_regime({"close":r.close,"ema20":r.ema20,"ema50":r.ema50,"ema200":r.ema200,"atr":r.atr})

async def crypto_setup(symbol: str):
    """Build a crypto setup from deterministic market data.

    AI confirmation is optional. A Gemini outage/quota/key problem must never
    turn a valid market-data setup into INSUFFICIENT_DATA.
    """
    df=crypto_klines(symbol)
    tech,tbias,atr,reasons=technical_score(df)
    regime=_regime(df)
    price=float(df.iloc[-1].close)
    # Numeric neutral whale evidence is required by direction_from_components.
    # The old string "NEUTRAL" caused a TypeError for every crypto symbol.
    preliminary=build_setup(symbol,"crypto",price,tech,50,50,tbias,0.0,atr,regime)
    try:
        ai=confirm(symbol,tech,tbias,50,0.0,price,atr)
    except Exception as exc:
        ai={"decision":"UNAVAILABLE","confidence":0,"rationale":f"Gemini unavailable: {type(exc).__name__}"}
    preliminary.gemini_confidence=float(ai.get("confidence",0) or 0)
    preliminary.gemini_decision=ai.get("decision")
    preliminary.gemini_rationale=ai.get("rationale","")
    preliminary.reasons=reasons+[f"Market regime: {regime}",f"Gemini confirmation: {ai.get('decision','UNAVAILABLE')} ({preliminary.gemini_confidence:.0f}/100)",ai.get("rationale","")]
    return preliminary

def stock_setup(symbol: str):
    df=stock_daily(symbol)
    tech,tbias,atr,reasons=technical_score(df)
    try:
        sentiment,sr=stock_sentiment(symbol)
    except Exception as exc:
        sentiment,sr=50,[f"stock sentiment unavailable: {type(exc).__name__}"]
    regime=_regime(df)
    s=build_setup(symbol,"stock",float(df.iloc[-1].close),tech,50,sentiment,tbias,0.0,atr,regime)
    s.reasons=reasons+sr+[f"Market regime: {regime}"]
    return s
