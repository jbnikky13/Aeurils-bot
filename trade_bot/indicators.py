import pandas as pd
import numpy as np


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    x=df.copy(); c=x['close']
    x['ema20']=c.ewm(span=20,adjust=False).mean(); x['ema50']=c.ewm(span=50,adjust=False).mean(); x['ema200']=c.ewm(span=200,adjust=False).mean()
    d=c.diff(); gain=d.clip(lower=0).ewm(alpha=1/14,adjust=False).mean(); loss=(-d.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean(); rs=gain/loss.replace(0,np.nan); x['rsi']=(100-100/(1+rs)).fillna(50)
    fast=c.ewm(span=12,adjust=False).mean(); slow=c.ewm(span=26,adjust=False).mean(); x['macd']=fast-slow; x['macd_signal']=x['macd'].ewm(span=9,adjust=False).mean(); x['macd_hist']=x['macd']-x['macd_signal']
    tr=pd.concat([x['high']-x['low'],(x['high']-c.shift()).abs(),(x['low']-c.shift()).abs()],axis=1).max(axis=1); x['atr']=tr.rolling(14).mean()
    up=x['high'].diff(); down=-x['low'].diff(); plus=up.where((up>down)&(up>0),0.0); minus=down.where((down>up)&(down>0),0.0); atr=x['atr'].replace(0,np.nan); x['plus_di']=100*plus.rolling(14).mean()/atr; x['minus_di']=100*minus.rolling(14).mean()/atr; dis=(x['plus_di']+x['minus_di']).replace(0,np.nan); x['adx']=(100*(x['plus_di']-x['minus_di']).abs()/dis).rolling(14).mean()
    x['vol_avg20']=x['volume'].rolling(20).mean(); x['volume_ratio']=x['volume']/x['vol_avg20'].replace(0,np.nan)
    mid=c.rolling(20).mean(); std=c.rolling(20).std(); x['bb_mid']=mid; x['bb_upper']=mid+2*std; x['bb_lower']=mid-2*std; width=(x['bb_upper']-x['bb_lower']).replace(0,np.nan); x['bb_position']=(c-x['bb_lower'])/width
    x['range_high20']=x['high'].rolling(20).max(); x['range_low20']=x['low'].rolling(20).min(); return x


def score(df: pd.DataFrame) -> tuple[int,float,float,list[str]]:
    x=enrich(df).dropna(subset=['ema20','ema50','ema200','atr'])
    if len(x)<30: raise ValueError('Insufficient candles for analysis')
    r=x.iloc[-1]; points=0; bias=0.0; reasons=[]
    if r.close>r.ema20>r.ema50>r.ema200: points+=25; bias+=.35; reasons.append('price above aligned EMA trend')
    elif r.close<r.ema20<r.ema50<r.ema200: points+=25; bias-=.35; reasons.append('price below aligned EMA trend')
    else: points+=10; reasons.append('mixed EMA structure')
    if 55<=r.rsi<=68: points+=15; bias+=.16; reasons.append(f'RSI bullish at {r.rsi:.0f}')
    elif 32<=r.rsi<=45: points+=15; bias-=.16; reasons.append(f'RSI bearish at {r.rsi:.0f}')
    else: points+=5; reasons.append(f'RSI {r.rsi:.0f} — neutral/extreme')
    if r.macd>r.macd_signal and r.macd_hist>0: points+=15; bias+=.15; reasons.append('MACD bullish with positive histogram')
    elif r.macd<r.macd_signal and r.macd_hist<0: points+=15; bias-=.15; reasons.append('MACD bearish with negative histogram')
    else: points+=5; reasons.append('MACD mixed')
    adx=float(r.adx) if pd.notna(r.adx) else 0
    if adx>=25:
        points+=15
        if r.plus_di>r.minus_di: bias+=.12; reasons.append(f'strong bullish trend: ADX {adx:.1f}')
        elif r.minus_di>r.plus_di: bias-=.12; reasons.append(f'strong bearish trend: ADX {adx:.1f}')
        else: reasons.append(f'strong trend: ADX {adx:.1f}, DI mixed')
    elif adx>=18: points+=8; reasons.append(f'developing trend: ADX {adx:.1f}')
    else: reasons.append(f'weak trend: ADX {adx:.1f}')
    vr=float(r.volume_ratio) if pd.notna(r.volume_ratio) else 0
    if vr>=1.2: points+=15; reasons.append(f'volume confirmation {vr:.2f}x average')
    elif vr>=.85: points+=8; reasons.append(f'normal volume {vr:.2f}x average')
    else: reasons.append(f'thin volume {vr:.2f}x average')
    return min(100,points),max(-1,min(1,bias)),float(r.atr),reasons


def strategy_context(df: pd.DataFrame) -> dict:
    x=enrich(df).dropna(subset=['ema20','ema50','ema200','atr'])
    if len(x)<30:return {}
    r=x.iloc[-1]; keys=['close','ema20','ema50','ema200','rsi','adx','plus_di','minus_di','atr','volume_ratio','bb_position','range_high20','range_low20']
    return {k:float(r[k]) for k in keys if pd.notna(r[k])}
