import os
from .market_data import crypto_klines, stock_daily
from .indicators import score as technical_score, enrich
from .signal_engine import build_setup
from .stock_sentiment import score as stock_sentiment
from .gemini_signal import confirm
from .market_regime import classify_regime


def _regime(df):
    r = enrich(df).iloc[-1]
    return classify_regime({"close": r.close, "ema20": r.ema20, "ema50": r.ema50, "ema200": r.ema200, "atr": r.atr})


async def crypto_setup(symbol: str):
    """Build a crypto setup from deterministic market data.

    Gemini confirmation is optional and advisory. Its outage/quota/key problem
    never converts a valid deterministic setup into insufficient data and is
    never counted as a zero-score market factor.
    """
    df = crypto_klines(symbol)
    tech, tbias, atr, reasons = technical_score(df)
    regime = _regime(df)
    price = float(df.iloc[-1].close)
    preliminary = build_setup(symbol, "crypto", price, tech, 50, 50, tbias, 0.0, atr, regime)

    ai = confirm(symbol, tech, tbias, 50, 0.0, price, atr)
    preliminary.gemini_confidence = ai.get("confidence")
    preliminary.gemini_decision = ai.get("decision")
    preliminary.gemini_rationale = ai.get("rationale", "")
    ai_state = "AVAILABLE" if ai.get("available") else "UNAVAILABLE"
    ai_conf = f"{float(ai['confidence']):.0f}/100" if ai.get("confidence") is not None else "not scored"
    preliminary.reasons = reasons + [
        f"Market regime: {regime}",
        f"Gemini confirmation: {ai.get('decision', 'UNAVAILABLE')} ({ai_conf}; {ai_state})",
        ai.get("rationale", ""),
    ]
    return preliminary


def stock_setup(symbol: str):
    df = stock_daily(symbol)
    tech, tbias, atr, reasons = technical_score(df)
    try:
        sentiment, sr = stock_sentiment(symbol)
    except Exception as exc:
        sentiment, sr = 50, [f"stock sentiment unavailable: {type(exc).__name__}"]
    regime = _regime(df)
    s = build_setup(symbol, "stock", float(df.iloc[-1].close), tech, 50, sentiment, tbias, 0.0, atr, regime)
    s.reasons = reasons + sr + [f"Market regime: {regime}"]
    return s
