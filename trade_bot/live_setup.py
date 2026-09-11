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


def _entry_context(df):
    x = enrich(df).dropna(subset=["ema20", "atr"])
    r = x.iloc[-1]
    recent = x.tail(5)
    return float(r.ema20), float(recent.high.max()), float(recent.low.min()), float(r.rsi)


async def crypto_setup(symbol: str):
    """Build a crypto setup with trend-aware entry validation.

    Gemini is advisory. A strong signal that is already overextended from its
    EMA20 is rejected rather than published as a chase entry.
    """
    df = crypto_klines(symbol)
    tech, tbias, atr, reasons = technical_score(df)
    regime = _regime(df)
    price = float(df.iloc[-1].close)
    ema20, recent_high, recent_low, rsi = _entry_context(df)
    preliminary = build_setup(symbol, "crypto", price, tech, 50, 50, tbias, 0.0, atr, regime,
                              ema20=ema20, recent_high=recent_high, recent_low=recent_low, rsi=rsi)

    ai = confirm(symbol, tech, tbias, 50, 0.0, price, atr)
    preliminary.gemini_confidence = ai.get("confidence")
    preliminary.gemini_decision = ai.get("decision")
    preliminary.gemini_rationale = ai.get("rationale", "")
    ai_state = "AVAILABLE" if ai.get("available") else "UNAVAILABLE"
    ai_conf = f"{float(ai['confidence']):.0f}/100" if ai.get("confidence") is not None else "not scored"
    preliminary.reasons = reasons + [
        f"Market regime: {regime}",
        f"Entry status: {preliminary.entry_status} ({preliminary.entry_quality:.0f}/100)" if preliminary.entry_quality is not None else f"Entry status: {preliminary.entry_status}",
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
    price = float(df.iloc[-1].close)
    ema20, recent_high, recent_low, rsi = _entry_context(df)
    s = build_setup(symbol, "stock", price, tech, 50, sentiment, tbias, 0.0, atr, regime,
                    ema20=ema20, recent_high=recent_high, recent_low=recent_low, rsi=rsi)
    s.reasons = reasons + sr + [f"Market regime: {regime}",
                                f"Entry status: {s.entry_status}" + (f" ({s.entry_quality:.0f}/100)" if s.entry_quality is not None else "")]
    return s
