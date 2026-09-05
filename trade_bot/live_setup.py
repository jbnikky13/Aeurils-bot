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
    """Build a Binance-listed crypto setup without requiring a manual wallet registry.
    Wallet-level intelligence is optional evidence; absence must not prevent technical/DEX analysis.
    """
    df=crypto_klines(symbol)
    tech,tbias,atr,reasons=technical_score(df)
    regime=_regime(df)
    # DEX/on-chain evidence is evaluated by confluence_providers in the scheduler.
    preliminary=build_setup(symbol,"crypto",float(df.iloc[-1].close),tech,50,"NEUTRAL",tbias,"NEUTRAL",atr,regime)
    ai=confirm(symbol,tech,tbias,50,"NEUTRAL",float(df.iloc[-1].close),atr)
    preliminary.gemini_confidence=float(ai.get("confidence",0)); preliminary.gemini_decision=ai.get("decision"); preliminary.gemini_rationale=ai.get("rationale","")
    if ai.get("decision") != preliminary.direction or preliminary.gemini_confidence < float(os.getenv("GEMINI_MIN_CONFIDENCE","70")):
        preliminary.direction="WAIT"; preliminary.entry_low=preliminary.entry_high=preliminary.stop_loss=preliminary.take_profit_1=preliminary.take_profit_2=None
        preliminary.invalidation="Gemini confirmation did not meet the configured confidence/consensus gate."
    preliminary.reasons=reasons+[f"Market regime: {regime}",f"Gemini confirmation: {ai.get('decision','UNKNOWN')} ({preliminary.gemini_confidence:.0f}/100)",ai.get("rationale","")]
    return preliminary

def stock_setup(symbol: str):
    df=stock_daily(symbol); tech,tbias,atr,reasons=technical_score(df); sentiment,sr=stock_sentiment(symbol); regime=_regime(df)
    s=build_setup(symbol,"stock",float(df.iloc[-1].close),tech,50,sentiment,tbias,0.0,atr,regime); s.reasons=reasons+[sr,f"Market regime: {regime}"]; return s
