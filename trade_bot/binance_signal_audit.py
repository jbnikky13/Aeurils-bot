"""Auditable Binance-wide scan results and deterministic daily ranking."""
from dataclasses import dataclass

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
        # A missing setup is an engine/data failure, not a market rejection.
        reasons=list(gate.get('failed',[])) if gate else ['Setup generation failed']
        unknown=list(gate.get('unknown',[])) if gate else ['Setup data unavailable']
        return ScanResult(symbol,'INSUFFICIENT_DATA',0,minimum,0.0,reasons,[],unknown)
    passed=int(gate.get('passed',0)) if gate else 0
    if gate and gate.get('actionable') and passed>=minimum and getattr(signal,'direction','WAIT')!='WAIT':
        status='QUALIFIED'
    elif gate and gate.get('unknown'):
        status='INSUFFICIENT_DATA'
    else:
        status='REJECTED'
    return ScanResult(symbol,status,passed,minimum,float(getattr(signal,'score',0) or 0),list(gate.get('confluences',[])),list(gate.get('failed',[])),list(gate.get('unknown',[])))

def rank(evaluated,minimum,limit=3):
    """Rank qualified setups by confluence, quality, R:R, liquidity and volatility."""
    qualified=[]
    for s,g in evaluated:
        if not s or not g.get('actionable') or g.get('passed',0)<minimum or getattr(s,'direction','WAIT')=='WAIT':
            continue
        rr=float(getattr(s,'risk_reward',0) or 0)
        score=float(getattr(s,'score',0) or 0)
        technical=float(getattr(s,'technical_score',0) or 0)
        # Confluence is primary; signal quality and R:R break ties.
        rank_key=(int(g.get('passed',0)), min(rr,5.0), score, technical)
        qualified.append((rank_key,s,g))
    qualified.sort(key=lambda x:x[0],reverse=True)
    return [(s,g) for _,s,g in qualified[:limit]]

def near_misses(evaluated,minimum,limit=5):
    """Return strongest directional setups below the strict gate for diagnostics."""
    rows=[]
    for s,g in evaluated:
        if not s or getattr(s,'direction','WAIT')=='WAIT': continue
        passed=int(g.get('passed',0))
        if passed>=minimum: continue
        rows.append(((passed,float(getattr(s,'score',0) or 0),float(getattr(s,'risk_reward',0) or 0)),s,g))
    rows.sort(key=lambda x:x[0],reverse=True)
    return [(s,g) for _,s,g in rows[:limit]]

def summary(results):
    counts={k:0 for k in ('QUALIFIED','REJECTED','INSUFFICIENT_DATA')}
    for r in results: counts[r.status]=counts.get(r.status,0)+1
    return counts
