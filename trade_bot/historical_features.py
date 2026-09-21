"""Feature engineering shared by historical research and setup matching."""
from __future__ import annotations
import numpy as np
import pandas as pd


def add_features(df):
    x=df.copy()
    close=x["close"]; high=x["high"]; low=x["low"]; volume=x["volume"]
    ret=close.pct_change()
    x["ret_1"]=ret
    x["ret_3"]=close.pct_change(3)
    x["ret_6"]=close.pct_change(6)
    x["ema20"]=close.ewm(span=20,adjust=False).mean()
    x["ema50"]=close.ewm(span=50,adjust=False).mean()
    tr=pd.concat([(high-low),(high-close.shift()).abs(),(low-close.shift()).abs()],axis=1).max(axis=1)
    x["atr14"]=tr.rolling(14).mean()
    x["atr_pct"]=x["atr14"]/close*100
    delta=close.diff()
    gain=delta.clip(lower=0).rolling(14).mean()
    loss=(-delta.clip(upper=0)).rolling(14).mean()
    rs=gain/loss.replace(0,np.nan)
    x["rsi14"]=100-(100/(1+rs))
    x["vol_mean20"]=volume.rolling(20).mean()
    x["volume_ratio"]=volume/x["vol_mean20"].replace(0,np.nan)
    x["taker_buy_ratio"]=x["taker_buy_base"]/volume.replace(0,np.nan)
    x["trade_intensity"]=x["trades"]/x["trades"].rolling(20).mean().replace(0,np.nan)
    x["range_pct"]=(high-low)/close*100
    x["breakout_20"]=close/close.rolling(20).max().shift(1)-1
    x["breakdown_20"]=close/close.rolling(20).min().shift(1)-1
    x["trend_gap_pct"]=(x["ema20"]-x["ema50"])/close*100
    return x.replace([np.inf,-np.inf],np.nan)


def feature_snapshot(df, index=-1):
    x=add_features(df).iloc[index]
    names=["ret_1","ret_3","ret_6","rsi14","atr_pct","volume_ratio",
           "taker_buy_ratio","trade_intensity","range_pct","breakout_20",
           "breakdown_20","trend_gap_pct"]
    return {n:float(x[n]) for n in names if pd.notna(x[n])}


def similarity(a,b):
    keys=["ret_1","ret_3","ret_6","rsi14","atr_pct","volume_ratio",
          "taker_buy_ratio","trade_intensity","range_pct","trend_gap_pct"]
    weights={"ret_1":1.0,"ret_3":1.2,"ret_6":1.4,"rsi14":0.8,"atr_pct":1.0,
             "volume_ratio":1.2,"taker_buy_ratio":1.0,"trade_intensity":0.8,
             "range_pct":0.8,"trend_gap_pct":1.2}
    ranges={"ret_1":.03,"ret_3":.08,"ret_6":.15,"rsi14":35,"atr_pct":8,
            "volume_ratio":3,"taker_buy_ratio":.5,"trade_intensity":3,
            "range_pct":8,"trend_gap_pct":10}
    score=0.0; total=0.0
    for k in keys:
        if k not in a or k not in b:
            continue
        d=abs(a[k]-b[k])/ranges[k]
        score += weights[k]*max(0.0,1.0-min(1.0,d))
        total += weights[k]
    return score/total if total else 0.0
