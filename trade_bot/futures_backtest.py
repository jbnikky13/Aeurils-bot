"""Historical Binance USD-M futures backtest for AURELIS continuation/runner modes.

Simulation only. 4H completed candles generate signals; 1H candles resolve
entries, stops, targets and ATR trailing. No orders are placed.
"""
from __future__ import annotations
import argparse, json, os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import requests
import pandas as pd
import numpy as np

BASE="https://fapi.binance.com"
UA={"User-Agent":"AURELIS-futures-backtest/1.0"}
TIMEOUT=20
LOOKBACK_DAYS=int(os.getenv("BACKTEST_DAYS","30"))
TOP_N=int(os.getenv("BACKTEST_SYMBOLS","20"))

def get(path, params):
    r=requests.get(BASE+path, params=params, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def klines(symbol, interval, limit=1000):
    raw=get("/fapi/v1/klines", {"symbol":symbol,"interval":interval,"limit":limit})
    cols=["open_time","open","high","low","close","volume","close_time","quote_volume","trades","taker_buy_volume","taker_buy_quote_volume","ignore"]
    df=pd.DataFrame(raw,columns=cols)
    for c in ["open","high","low","close","volume","quote_volume","taker_buy_volume","taker_buy_quote_volume"]:
        df[c]=pd.to_numeric(df[c],errors="coerce")
    df["time"]=pd.to_datetime(df["open_time"],unit="ms",utc=True)
    return df

def stats_oi(symbol):
    try: raw=get("/futures/data/openInterestHist", {"symbol":symbol,"period":"4h","limit":500})
    except Exception: return pd.DataFrame()
    df=pd.DataFrame(raw)
    if df.empty:return df
    df["time"]=pd.to_datetime(pd.to_numeric(df["timestamp"]),unit="ms",utc=True)
    df["oi"]=pd.to_numeric(df["sumOpenInterest"],errors="coerce")
    df["oi_change_pct"]=df["oi"].pct_change()*100
    return df[["time","oi_change_pct"]].dropna()

def stats_taker(symbol):
    try: raw=get("/futures/data/takerlongshortRatio", {"symbol":symbol,"period":"4h","limit":500})
    except Exception: return pd.DataFrame()
    df=pd.DataFrame(raw)
    if df.empty or "timestamp" not in df or "buySellRatio" not in df:return pd.DataFrame()
    df["time"]=pd.to_datetime(pd.to_numeric(df["timestamp"]),unit="ms",utc=True)
    df["taker_ratio"]=pd.to_numeric(df["buySellRatio"],errors="coerce")
    return df[["time","taker_ratio"]].dropna()

def indicators(df):
    x=df.copy(); close=x.close
    x["ema20"]=close.ewm(span=20,adjust=False).mean(); x["ema50"]=close.ewm(span=50,adjust=False).mean(); x["ema200"]=close.ewm(span=200,adjust=False).mean()
    delta=close.diff(); gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean(); loss=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean(); rs=gain/loss.replace(0,np.nan)
    x["rsi"]=(100-(100/(1+rs))).fillna(50)
    tr=pd.concat([(x.high-x.low),(x.high-close.shift()).abs(),(x.low-close.shift()).abs()],axis=1).max(axis=1); x["atr"]=tr.ewm(alpha=1/14,adjust=False).mean()
    ema12=close.ewm(span=12,adjust=False).mean(); ema26=close.ewm(span=26,adjust=False).mean(); macd=ema12-ema26; x["macd_hist"]=macd-macd.ewm(span=9,adjust=False).mean()
    up=x.high.diff(); down=-x.low.diff(); plus_dm=np.where((up>down)&(up>0),up,0.0); minus_dm=np.where((down>up)&(down>0),down,0.0); atr14=x["atr"].replace(0,np.nan)
    plus_di=100*pd.Series(plus_dm,index=x.index).ewm(alpha=1/14,adjust=False).mean()/atr14; minus_di=100*pd.Series(minus_dm,index=x.index).ewm(alpha=1/14,adjust=False).mean()/atr14
    dx=(100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,np.nan)).fillna(0); x["adx"]=dx.ewm(alpha=1/14,adjust=False).mean(); x["volume_ratio"]=x.volume/x.volume.rolling(20).mean()
    return x

def continuation(row, prior, direction, oi, taker):
    atr=float(row.atr); close=float(row.close)
    if atr<=0 or close<=0:return ("NORMAL",0,False)
    prev_high=float(prior.tail(20).high.max()); prev_low=float(prior.tail(20).low.min()); buffer=.10*atr
    trend=(close>row.ema20>row.ema50>row.ema200) if direction=="LONG" else (close<row.ema20<row.ema50<row.ema200)
    breakout=(close>prev_high+buffer) if direction=="LONG" else (close<prev_low-buffer)
    momentum=(row.macd_hist>0 and row.rsi>=45) if direction=="LONG" else (row.macd_hist<0 and row.rsi<=55)
    volume=row.volume_ratio>=1.20; accel=row.volume_ratio>=1.50; strong=row.adx>=25
    oi_ok=oi is not None and oi>=.50; taker_ok=taker is not None and ((taker>1.03) if direction=="LONG" else (taker<.97)); flow=oi_ok or taker_ok
    score=25*int(trend)+20*int(breakout)+15*int(momentum)+15*int(volume)+15*int(flow)+10*int(strong and accel)
    mode="BREAKOUT" if score>=70 and trend and breakout and momentum else ("CONTINUATION" if score>=70 and trend and strong and momentum else "NORMAL")
    return mode,int(score),bool(trend)

@dataclass
class Trade:
    symbol:str; direction:str; mode:str; score:int; entry_time:str; entry:float; stop:float; tp1:float; tp2:float
    outcome:str="OPEN"; exit_time:str=""; exit:float=0; pnl_pct:float=0; realized_pct:float=0; remaining_pct:float=100
    max_favorable_pct:float=0; max_adverse_pct:float=0; bars:int=0

def simulate(trade, hourly):
    remaining=100.0; realized=0.0; trail=None; runner=False
    for _,c in hourly.iterrows():
        if c.time <= pd.Timestamp(trade.entry_time): continue
        trade.bars+=1; high,low,close,atr=map(float,(c.high,c.low,c.close,c.atr))
        favorable=((high-trade.entry)/trade.entry*100 if trade.direction=="LONG" else (trade.entry-low)/trade.entry*100); adverse=((trade.entry-low)/trade.entry*100 if trade.direction=="LONG" else (high-trade.entry)/trade.entry*100)
        trade.max_favorable_pct=max(trade.max_favorable_pct,max(0,favorable)); trade.max_adverse_pct=max(trade.max_adverse_pct,max(0,adverse))
        stop_hit=(low<=trade.stop) if trade.direction=="LONG" else (high>=trade.stop); tp1_hit=(high>=trade.tp1) if trade.direction=="LONG" else (low<=trade.tp1); tp2_hit=(high>=trade.tp2) if trade.direction=="LONG" else (low<=trade.tp2)
        if stop_hit and (tp1_hit or tp2_hit): trade.outcome="AMBIGUOUS"; trade.exit_time=str(c.time); trade.exit=close; return trade
        if stop_hit:
            trade.outcome="LOSS_SL"; trade.exit_time=str(c.time); trade.exit=trade.stop; move=((trade.stop-trade.entry)/trade.entry*100 if trade.direction=="LONG" else (trade.entry-trade.stop)/trade.entry*100); trade.realized_pct=realized; trade.pnl_pct=realized+remaining/100*move; return trade
        if remaining>70 and tp1_hit:
            move=((trade.tp1-trade.entry)/trade.entry*100 if trade.direction=="LONG" else (trade.entry-trade.tp1)/trade.entry*100); realized += .30*move; remaining=70; trail=trade.entry
        if remaining>40 and tp2_hit:
            move=((trade.tp2-trade.entry)/trade.entry*100 if trade.direction=="LONG" else (trade.entry-trade.tp2)/trade.entry*100); realized += .30*move; remaining=40; runner=True
            if atr>0: trail=(close-2*atr) if trade.direction=="LONG" else (close+2*atr)
        if runner:
            proposed=(close-2*atr) if trade.direction=="LONG" else (close+2*atr); trail=max(trail,proposed) if trade.direction=="LONG" else min(trail,proposed); trail_hit=(low<=trail) if trade.direction=="LONG" else (high>=trail)
            if trail_hit:
                trade.outcome="WIN_RUNNER"; trade.exit_time=str(c.time); trade.exit=trail; move=((trail-trade.entry)/trade.entry*100 if trade.direction=="LONG" else (trade.entry-trail)/trade.entry*100); trade.realized_pct=realized; trade.pnl_pct=realized+.40*move; return trade
        if trade.bars>=24:
            trade.outcome="EXPIRED"; trade.exit_time=str(c.time); trade.exit=close; move=((close-trade.entry)/trade.entry*100 if trade.direction=="LONG" else (trade.entry-close)/trade.entry*100); trade.pnl_pct=realized+remaining/100*move; return trade
    return trade

def symbols(limit=None):
    info=get("/fapi/v1/exchangeInfo",{}); allowed={s["symbol"] for s in info["symbols"] if s.get("contractType")=="PERPETUAL" and s.get("status")=="TRADING" and s.get("quoteAsset")=="USDT"}
    tick=get("/fapi/v1/ticker/24hr",{}); rows=[x for x in tick if x.get("symbol") in allowed and float(x.get("quoteVolume",0))>0]; rows.sort(key=lambda x:float(x.get("quoteVolume",0)),reverse=True); return [x["symbol"] for x in rows[:(limit or TOP_N)]]

def run(days=LOOKBACK_DAYS, symbol_count=TOP_N):
    all_trades=[]; universe=symbols(symbol_count)
    for i,symbol in enumerate(universe,1):
        try:
            h4=indicators(klines(symbol,"4h",1000)); h1=indicators(klines(symbol,"1h",1000)); oi=stats_oi(symbol); tk=stats_taker(symbol)
            if not oi.empty: h4=pd.merge_asof(h4.sort_values("time"),oi.sort_values("time"),on="time",direction="backward",tolerance=pd.Timedelta(hours=4))
            else: h4["oi_change_pct"]=np.nan
            if not tk.empty: h4=pd.merge_asof(h4.sort_values("time"),tk.sort_values("time"),on="time",direction="backward",tolerance=pd.Timedelta(hours=4))
            else: h4["taker_ratio"]=np.nan
            cutoff=pd.Timestamp.now(tz="UTC")-pd.Timedelta(days=days); h4=h4[h4.time>=cutoff].reset_index(drop=True)
            for j in range(30,len(h4)):
                r=h4.iloc[j];
                if pd.isna(r.atr) or pd.isna(r.volume_ratio): continue
                oi_v=None if pd.isna(r.get("oi_change_pct")) else float(r.get("oi_change_pct")); tk_v=None if pd.isna(r.get("taker_ratio")) else float(r.get("taker_ratio"))
                for direction in ("LONG","SHORT"):
                    mode,score,_=continuation(r,h4.iloc[:j],direction,oi_v,tk_v)
                    if mode=="NORMAL": continue
                    atr=float(r.atr); future=h1[h1.time>r.time]
                    if future.empty: continue
                    entry=float(future.iloc[0].open)
                    if direction=="LONG": stop=min(entry-1.8*atr,float(r.low)-.25*atr); tp1=entry+2*atr; tp2=entry+4*atr
                    else: stop=max(entry+1.8*atr,float(r.high)+.25*atr); tp1=entry-2*atr; tp2=entry-4*atr
                    if min(stop,tp1,tp2)<=0: continue
                    all_trades.append(simulate(Trade(symbol,direction,mode,score,str(future.iloc[0].time),entry,stop,tp1,tp2),future))
            print(f"{i}/{len(universe)} {symbol}: cumulative signals={len(all_trades)}",flush=True)
        except Exception as exc: print(f"{symbol}: ERROR {exc}",flush=True)
    closed=[t for t in all_trades if t.outcome not in ("OPEN","AMBIGUOUS")]; wins=[t for t in closed if t.pnl_pct>0]; by={}
    for mode in ("BREAKOUT","CONTINUATION"):
        xs=[t for t in closed if t.mode==mode]; by[mode]={"trades":len(xs),"win_rate":round(100*sum(t.pnl_pct>0 for t in xs)/len(xs),2) if xs else 0,"avg_pnl_pct":round(sum(t.pnl_pct for t in xs)/len(xs),4) if xs else 0,"total_pnl_pct":round(sum(t.pnl_pct for t in xs),4) if xs else 0}
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"days":days,"symbols_requested":symbol_count,"symbols_tested":universe,"trades":len(all_trades),"closed_trades":len(closed),"ambiguous":sum(t.outcome=="AMBIGUOUS" for t in all_trades),"overall":{"win_rate":round(100*len(wins)/len(closed),2) if closed else 0,"avg_pnl_pct":round(sum(t.pnl_pct for t in closed)/len(closed),4) if closed else 0,"total_pnl_pct":round(sum(t.pnl_pct for t in closed),4) if closed else 0},"by_mode":by,"trades_detail":[asdict(t) for t in all_trades]}

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--days",type=int,default=LOOKBACK_DAYS); p.add_argument("--symbols",type=int,default=TOP_N); a=p.parse_args(); print(json.dumps(run(a.days,a.symbols),indent=2))
