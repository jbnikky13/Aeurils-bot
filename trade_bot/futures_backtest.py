"""Offline-friendly Binance USD-M futures continuation backtest.

Uses Binance Vision public futures kline archives instead of live REST endpoints.
Signals use completed 4H candles; subsequent 1H candles resolve entries, stops,
targets and the ATR trailing runner. Open interest is not fabricated; the kline
taker-buy volume is used as a directional flow proxy for this historical test.
"""
from __future__ import annotations
import argparse, io, json, os, zipfile
from dataclasses import dataclass, asdict
from datetime import date, timedelta, datetime, timezone
import requests
import pandas as pd
import numpy as np

BASE="https://data.binance.vision/data/futures/um"
DEFAULT_SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","BNBUSDT","DOGEUSDT","ADAUSDT","SUIUSDT","LINKUSDT","BRUSDT"]
LOOKBACK_DAYS=int(os.getenv("BACKTEST_DAYS","30")); SYMBOL_COUNT=int(os.getenv("BACKTEST_SYMBOLS","10")); TIMEOUT=30
HEADERS={"User-Agent":"AURELIS-futures-backtest/1.0"}

def _download(url):
    r=requests.get(url,headers=HEADERS,timeout=TIMEOUT)
    if r.status_code==404:return None
    r.raise_for_status(); return r.content

def _read_zip(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names=[n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names: raise ValueError("Binance Vision archive contains no CSV")
        with z.open(names[0]) as f:return pd.read_csv(f,header=None)

def _kline_frame(raw):
    cols=["open_time","open","high","low","close","volume","close_time","quote_volume","trades","taker_buy_volume","taker_buy_quote_volume","ignore"]
    if raw.shape[1]<len(cols):raise ValueError(f"Unexpected kline columns: {raw.shape[1]}")
    raw=raw.iloc[:,:len(cols)].copy(); raw.columns=cols
    for c in ["open","high","low","close","volume","quote_volume","taker_buy_volume","taker_buy_quote_volume"]:raw[c]=pd.to_numeric(raw[c],errors="coerce")
    raw["time"]=pd.to_datetime(pd.to_numeric(raw["open_time"]),unit="ms",utc=True)
    return raw.dropna(subset=["time","open","high","low","close","volume"])

def _dates(start,end):
    d=start
    while d<=end:yield d; d+=timedelta(days=1)

def load_klines(symbol,interval,start,end):
    frames=[]; months={(d.year,d.month) for d in _dates(start,end)}
    for year,month in sorted(months):
        month_start=date(year,month,1); next_month=date(year+1,1,1) if month==12 else date(year,month+1,1); month_end=next_month-timedelta(days=1)
        loaded=False
        if month_end<date.today():
            url=f"{BASE}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{year:04d}-{month:02d}.zip"
            try:
                blob=_download(url)
                if blob:frames.append(_kline_frame(_read_zip(blob))); loaded=True
            except Exception:loaded=False
        if not loaded:
            for d in _dates(max(start,month_start),min(end,month_end)):
                url=f"{BASE}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{d.isoformat()}.zip"
                try:
                    blob=_download(url)
                    if blob:frames.append(_kline_frame(_read_zip(blob)))
                except Exception:continue
    if not frames:return pd.DataFrame()
    out=pd.concat(frames,ignore_index=True).drop_duplicates("time").sort_values("time")
    return out[(out.time>=pd.Timestamp(start,tz="UTC"))&(out.time<pd.Timestamp(end+timedelta(days=1),tz="UTC"))].reset_index(drop=True)

def indicators(df):
    x=df.copy(); close=x.close
    x["ema20"]=close.ewm(span=20,adjust=False).mean(); x["ema50"]=close.ewm(span=50,adjust=False).mean(); x["ema200"]=close.ewm(span=200,adjust=False).mean()
    delta=close.diff(); gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean(); loss=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean(); rs=gain/loss.replace(0,np.nan); x["rsi"]=(100-(100/(1+rs))).fillna(50)
    tr=pd.concat([(x.high-x.low),(x.high-close.shift()).abs(),(x.low-close.shift()).abs()],axis=1).max(axis=1); x["atr"]=tr.ewm(alpha=1/14,adjust=False).mean()
    ema12=close.ewm(span=12,adjust=False).mean(); ema26=close.ewm(span=26,adjust=False).mean(); macd=ema12-ema26; x["macd_hist"]=macd-macd.ewm(span=9,adjust=False).mean()
    up=x.high.diff(); down=-x.low.diff(); plus_dm=np.where((up>down)&(up>0),up,0.0); minus_dm=np.where((down>up)&(down>0),down,0.0); atr14=x["atr"].replace(0,np.nan)
    plus_di=100*pd.Series(plus_dm,index=x.index).ewm(alpha=1/14,adjust=False).mean()/atr14; minus_di=100*pd.Series(minus_dm,index=x.index).ewm(alpha=1/14,adjust=False).mean()/atr14; dx=(100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,np.nan)).fillna(0); x["adx"]=dx.ewm(alpha=1/14,adjust=False).mean(); x["volume_ratio"]=x.volume/x.volume.rolling(20).mean()
    sell=(x.volume-x.taker_buy_volume).clip(lower=0); x["taker_ratio"]=x.taker_buy_volume/sell.replace(0,np.nan)
    return x

def continuation(row,prior,direction,taker):
    atr=float(row.atr); close=float(row.close)
    if atr<=0 or close<=0:return "NORMAL",0
    prev_high=float(prior.tail(20).high.max()); prev_low=float(prior.tail(20).low.min()); buffer=.10*atr
    trend=(close>row.ema20>row.ema50>row.ema200) if direction=="LONG" else (close<row.ema20<row.ema50<row.ema200); breakout=(close>prev_high+buffer) if direction=="LONG" else (close<prev_low-buffer); momentum=(row.macd_hist>0 and row.rsi>=45) if direction=="LONG" else (row.macd_hist<0 and row.rsi<=55); volume=row.volume_ratio>=1.20; accel=row.volume_ratio>=1.50; strong=row.adx>=25; flow=taker is not None and ((taker>1.03) if direction=="LONG" else (taker<.97))
    score=25*int(trend)+20*int(breakout)+15*int(momentum)+15*int(volume)+15*int(flow)+10*int(strong and accel); mode="BREAKOUT" if score>=70 and trend and breakout and momentum else ("CONTINUATION" if score>=70 and trend and strong and momentum else "NORMAL")
    return mode,int(score)

@dataclass
class Trade:
    symbol:str; direction:str; mode:str; score:int; entry_time:str; entry:float; stop:float; tp1:float; tp2:float
    outcome:str="OPEN"; exit_time:str=""; exit:float=0; pnl_pct:float=0; max_favorable_pct:float=0; max_adverse_pct:float=0

def simulate(t,h1):
    remaining=100.0; realized=0.0; trail=None; runner=False; bars=0
    for _,c in h1.iterrows():
        if c.time<=pd.Timestamp(t.entry_time):continue
        bars+=1; high,low,close,atr=map(float,(c.high,c.low,c.close,c.atr)); fav=((high-t.entry)/t.entry*100 if t.direction=="LONG" else (t.entry-low)/t.entry*100); adv=((t.entry-low)/t.entry*100 if t.direction=="LONG" else (high-t.entry)/t.entry*100); t.max_favorable_pct=max(t.max_favorable_pct,max(0,fav)); t.max_adverse_pct=max(t.max_adverse_pct,max(0,adv))
        stop_hit=(low<=t.stop) if t.direction=="LONG" else (high>=t.stop); tp1=(high>=t.tp1) if t.direction=="LONG" else (low<=t.tp1); tp2=(high>=t.tp2) if t.direction=="LONG" else (low<=t.tp2)
        if stop_hit and (tp1 or tp2):t.outcome="AMBIGUOUS";t.exit_time=str(c.time);t.exit=close;return t
        if stop_hit:
            t.outcome="LOSS_SL";t.exit_time=str(c.time);t.exit=t.stop;move=((t.stop-t.entry)/t.entry*100 if t.direction=="LONG" else (t.entry-t.stop)/t.entry*100);t.pnl_pct=realized+remaining/100*move;return t
        if remaining>70 and tp1:
            move=((t.tp1-t.entry)/t.entry*100 if t.direction=="LONG" else (t.entry-t.tp1)/t.entry*100);realized+=.30*move;remaining=70;trail=t.entry
        if remaining>40 and tp2:
            move=((t.tp2-t.entry)/t.entry*100 if t.direction=="LONG" else (t.entry-t.tp2)/t.entry*100);realized+=.30*move;remaining=40;runner=True;trail=(close-2*atr) if t.direction=="LONG" else (close+2*atr)
        if runner:
            proposed=(close-2*atr) if t.direction=="LONG" else (close+2*atr);trail=max(trail,proposed) if t.direction=="LONG" else min(trail,proposed);hit=(low<=trail) if t.direction=="LONG" else (high>=trail)
            if hit:
                t.outcome="WIN_RUNNER";t.exit_time=str(c.time);t.exit=trail;move=((trail-t.entry)/t.entry*100 if t.direction=="LONG" else (t.entry-trail)/t.entry*100);t.pnl_pct=realized+.40*move;return t
        if bars>=24:
            t.outcome="EXPIRED";t.exit_time=str(c.time);t.exit=close;move=((close-t.entry)/t.entry*100 if t.direction=="LONG" else (t.entry-close)/t.entry*100);t.pnl_pct=realized+remaining/100*move;return t
    return t

def run(days=LOOKBACK_DAYS,symbol_count=SYMBOL_COUNT):
    end=date.today()-timedelta(days=1);start=end-timedelta(days=days-1);universe=DEFAULT_SYMBOLS[:symbol_count];trades=[]
    for i,symbol in enumerate(universe,1):
        try:
            h4=indicators(load_klines(symbol,"4h",start-timedelta(days=20),end));h1=indicators(load_klines(symbol,"1h",start,end))
            if len(h4)<40 or len(h1)<30:print(f"{symbol}: insufficient Vision data",flush=True);continue
            h4=h4[h4.time>=pd.Timestamp(start,tz="UTC")].reset_index(drop=True)
            for j in range(30,len(h4)):
                r=h4.iloc[j]
                if any(pd.isna(r[k]) for k in ["atr","volume_ratio","ema200","adx"]):continue
                for direction in ("LONG","SHORT"):
                    mode,score=continuation(r,h4.iloc[:j],direction,float(r.taker_ratio) if pd.notna(r.taker_ratio) else None)
                    if mode=="NORMAL":continue
                    future=h1[h1.time>r.time]
                    if future.empty:continue
                    entry=float(future.iloc[0].open);atr=float(r.atr)
                    if direction=="LONG":stop=min(entry-1.8*atr,float(r.low)-.25*atr);tp1=entry+2*atr;tp2=entry+4*atr
                    else:stop=max(entry+1.8*atr,float(r.high)+.25*atr);tp1=entry-2*atr;tp2=entry-4*atr
                    if min(stop,tp1,tp2)<=0:continue
                    trades.append(simulate(Trade(symbol,direction,mode,score,str(future.iloc[0].time),entry,stop,tp1,tp2),future))
            print(f"{i}/{len(universe)} {symbol}: signals={len(trades)}",flush=True)
        except Exception as exc:print(f"{symbol}: ERROR {exc}",flush=True)
    closed=[t for t in trades if t.outcome not in ("OPEN","AMBIGUOUS")];by={}
    for mode in ("BREAKOUT","CONTINUATION"):
        xs=[t for t in closed if t.mode==mode];by[mode]={"trades":len(xs),"win_rate":round(100*sum(t.pnl_pct>0 for t in xs)/len(xs),2) if xs else 0,"avg_pnl_pct":round(sum(t.pnl_pct for t in xs)/len(xs),4) if xs else 0,"total_pnl_pct":round(sum(t.pnl_pct for t in xs),4) if xs else 0}
    overall={"win_rate":round(100*sum(t.pnl_pct>0 for t in closed)/len(closed),2) if closed else 0,"avg_pnl_pct":round(sum(t.pnl_pct for t in closed)/len(closed),4) if closed else 0,"total_pnl_pct":round(sum(t.pnl_pct for t in closed),4) if closed else 0}
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"days":days,"start":start.isoformat(),"end":end.isoformat(),"symbols_tested":universe,"trades":len(trades),"closed_trades":len(closed),"ambiguous":sum(t.outcome=="AMBIGUOUS" for t in trades),"overall":overall,"by_mode":by,"trades_detail":[asdict(t) for t in trades]}

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--days",type=int,default=LOOKBACK_DAYS);p.add_argument("--symbols",type=int,default=SYMBOL_COUNT);a=p.parse_args();print(json.dumps(run(a.days,a.symbols),indent=2))
