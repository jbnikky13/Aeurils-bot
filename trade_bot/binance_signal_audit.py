"""Auditable Binance-wide scan results and deterministic daily ranking."""
from dataclasses import dataclass,asdict
from typing import Any

@dataclass
class ScanResult:
    symbol:str
    status:str
    confluences:int
    minimum:int
    score:float
    reasons:list[str]
    failed:list[str]
    unknown:list[str]

def classify(symbol,signal,gate,minimum):
    if signal is None:
        return ScanResult(symbol,'INSUFFICIENT_DATA',0,minimum,0.0,['Setup data unavailable'],[],[])
    status='QUALIFIED' if gate.get('actionable') and gate.get('passed',0)>=minimum else ('INSUFFICIENT_DATA' if gate.get('unknown') else 'REJECTED')
    return ScanResult(symbol,status,int(gate.get('passed',0)),minimum,float(getattr(signal,'score',0) or 0),list(gate.get('confluences',[])),list(gate.get('failed',[])),list(gate.get('unknown',[])))

def rank(evaluated,minimum,limit=3):
    qualified=[(s,g) for s,g in evaluated if g.get('actionable') and g.get('passed',0)>=minimum and getattr(s,'direction','WAIT')!='WAIT']
    qualified.sort(key=lambda x:(int(x[1].get('passed',0)),float(getattr(x[0],'score',0) or 0)),reverse=True)
    return qualified[:limit]

def summary(results):
    counts={k:0 for k in ('QUALIFIED','REJECTED','INSUFFICIENT_DATA')}
    for r in results: counts[r.status]=counts.get(r.status,0)+1
    return counts
