"""Deterministic market-regime classification from OHLCV/indicator data."""
import os

def classify_regime(indicators):
    close=float(indicators.get("close",0) or 0); ema20=float(indicators.get("ema20",0) or 0); ema50=float(indicators.get("ema50",0) or 0); ema200=float(indicators.get("ema200",0) or 0); atr=float(indicators.get("atr",0) or 0)
    if not close or not ema20 or not ema50: return "UNKNOWN"
    if atr/close >= float(os.getenv("HIGH_VOL_ATR_PCT","0.04")): return "HIGH_VOLATILITY"
    if ema20>ema50 and (not ema200 or ema50>ema200) and close>ema20: return "BULLISH"
    if ema20<ema50 and (not ema200 or ema50<ema200) and close<ema20: return "BEARISH"
    return "SIDEWAYS"
