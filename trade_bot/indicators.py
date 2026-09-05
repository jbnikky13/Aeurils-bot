import pandas as pd
import numpy as np


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    close = x["close"]
    x["ema20"] = close.ewm(span=20, adjust=False).mean()
    x["ema50"] = close.ewm(span=50, adjust=False).mean()
    x["ema200"] = close.ewm(span=200, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    x["rsi"] = (100 - (100 / (1 + rs))).fillna(50)
    fast = close.ewm(span=12, adjust=False).mean()
    slow = close.ewm(span=26, adjust=False).mean()
    x["macd"] = fast - slow
    x["macd_signal"] = x["macd"].ewm(span=9, adjust=False).mean()
    tr = pd.concat([x["high"]-x["low"], (x["high"]-close.shift()).abs(), (x["low"]-close.shift()).abs()], axis=1).max(axis=1)
    x["atr"] = tr.rolling(14).mean()
    x["vol_avg20"] = x["volume"].rolling(20).mean()
    return x


def score(df: pd.DataFrame) -> tuple[int, float, float, list[str]]:
    x = enrich(df).dropna(subset=["ema20","ema50","ema200","atr"])
    if len(x) < 5:
        raise ValueError("Insufficient candles for analysis")
    r = x.iloc[-1]
    points = 0
    bias = 0.0
    reasons = []
    if r.close > r.ema20 > r.ema50 > r.ema200:
        points += 30; bias += .35; reasons.append("price above aligned EMA trend")
    elif r.close < r.ema20 < r.ema50 < r.ema200:
        points += 30; bias -= .35; reasons.append("price below aligned EMA trend")
    else:
        points += 15; reasons.append("mixed EMA structure")
    if r.rsi >= 55 and r.rsi <= 70:
        points += 20; bias += .18; reasons.append(f"RSI bullish at {r.rsi:.0f}")
    elif r.rsi <= 45 and r.rsi >= 30:
        points += 20; bias -= .18; reasons.append(f"RSI bearish at {r.rsi:.0f}")
    else:
        points += 10; reasons.append(f"RSI {r.rsi:.0f}")
    macd_delta = r.macd - r.macd_signal
    if macd_delta > 0:
        points += 20; bias += .15; reasons.append("MACD bullish")
    else:
        points += 20; bias -= .15; reasons.append("MACD bearish")
    if r.volume > r.vol_avg20:
        points += 20; reasons.append("volume above 20-period average")
    else:
        points += 10; reasons.append("volume below 20-period average")
    return min(100, points), max(-1, min(1, bias)), float(r.atr), reasons
