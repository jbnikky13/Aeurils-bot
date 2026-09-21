"""Historical setup matcher and outcome estimator for AURELIS.

This module is advisory research only. It never changes a signal direction by
itself and never submits orders. It compares a current feature snapshot with
prior Binance candles and measures what happened after similar states.
"""
from __future__ import annotations
from collections import defaultdict
import math
from .historical_features import add_features, feature_snapshot, similarity


def _forward_outcome(df, i, direction, horizon=6):
    row=df.iloc[i]
    entry=float(row.close)
    atr=float(row.atr14 or 0)
    if entry<=0 or atr<=0:
        return None
    stop=entry-1.5*atr if direction=="LONG" else entry+1.5*atr
    tp1=entry+2*atr if direction=="LONG" else entry-2*atr
    future=df.iloc[i+1:i+1+horizon]
    for _,r in future.iterrows():
        hit_sl=float(r.low)<=stop if direction=="LONG" else float(r.high)>=stop
        hit_tp=float(r.high)>=tp1 if direction=="LONG" else float(r.low)<=tp1
        if hit_sl and hit_tp:
            # Conservative ordering when one OHLC candle touches both levels.
            return -1.0
        if hit_sl:
            return -1.0
        if hit_tp:
            return 1.0
    return None


def match(df, current=None, direction="LONG", lookback=720, top_k=100, min_similarity=.72):
    x=add_features(df).reset_index(drop=True)
    if len(x)<80:
        return {"matches":0,"win_rate_pct":0.0,"avg_outcome_r":0.0,"sample_warning":"insufficient history"}
    current=feature_snapshot(x) if current is None else current
    start=max(60,len(x)-lookback)
    candidates=[]
    for i in range(start, len(x)-7):
        snap=feature_snapshot(x,i)
        sim=similarity(current,snap)
        if sim>=min_similarity:
            outcome=_forward_outcome(x,i,direction)
            if outcome is not None:
                candidates.append((sim,outcome,i))
    candidates=sorted(candidates,reverse=True)[:top_k]
    if not candidates:
        return {"matches":0,"win_rate_pct":0.0,"avg_outcome_r":0.0,"sample_warning":"no sufficiently similar historical setups"}
    outcomes=[o for _,o,_ in candidates]
    return {
        "matches":len(candidates),
        "win_rate_pct":round(sum(o>0 for o in outcomes)/len(outcomes)*100,2),
        "avg_outcome_r":round(sum(outcomes)/len(outcomes),4),
        "median_similarity":round(sorted(s for s,_,_ in candidates)[len(candidates)//2],4),
        "sample_warning":"small sample" if len(candidates)<30 else None,
    }
