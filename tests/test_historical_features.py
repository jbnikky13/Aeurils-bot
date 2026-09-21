import pandas as pd
import numpy as np

from trade_bot.historical_features import add_features, similarity


def candles(n=100):
    close=np.linspace(100,120,n)
    return pd.DataFrame({
        "open_time":pd.date_range("2026-01-01",periods=n,freq="4h"),
        "open":close-0.5,"high":close+1,"low":close-1,"close":close,
        "volume":np.linspace(1000,2000,n),"trades":np.arange(100,200),
        "taker_buy_base":np.linspace(500,1200,n),
        "taker_buy_quote":np.linspace(50000,120000,n),
    })


def test_features_exist_and_similarity_is_bounded():
    x=add_features(candles())
    for name in ("ema20","ema50","atr14","rsi14","volume_ratio","taker_buy_ratio","trade_intensity"):
        assert name in x.columns
    snap={k:float(x.iloc[-1][k]) for k in ("ret_1","ret_3","ret_6","rsi14","atr_pct","volume_ratio","taker_buy_ratio","trade_intensity","range_pct","trend_gap_pct")}
    assert 0 <= similarity(snap,snap) <= 1
    assert similarity(snap,snap) == 1.0
