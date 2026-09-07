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
    tier:str='REJECTED'

def classify(symbol,signal,gate,minimum):
    if signal is None:
        reasons=list(gate.get('failed',[])) if gate else ['Setup generation failed']
        unknown=list(gate.get('unknown',[])) if gate else ['Setup data unavailable']
        return ScanResult(symbol,'INSUFFICIENT_DATA',0,minimum,0.0,reasons,[],unknown,'INSUFFICIENT_DATA')
    passed=int(gate.get('passed',0)) if gate else 0
    tier=str(gate.get('tier','REJECTED')) if gate else 'REJECTED'
    if tier in ('A_PLUS','A_SETUP') and gate.get('actionable') and getattr(signal,'direction','WAIT')!='WAIT':
        status='QUALIFIED'
    elif tier=='EARLY_SETUP':
        status='EARLY_SETUP'
    elif gate and gate.get('unknown'):
        status='INSUFFICIENT_DATA'
    else:
        status='REJECTED'
    return ScanResult(symbol,status,passed,minimum,float(gate.get('score',getattr(signal,'score',0)) or 0),list(gate.get('confluences',[])),list(gate.get('failed',[])),list(gate.get('unknown',[])),tier)

def rank(evaluated,minimum,limit=3):
    """Rank actionable setups by weighted score, then R:R and technical quality."""
    candidates=[]
    for s,g in evaluated:
        if not s or not g.get('actionable') or getattr(s,'direction','WAIT')=='WAIT':
            continue
        rr=float(getattr(s,'risk_reward',0) or 0)
        score=float(g.get('score',getattr(s,'score',0)) or 0)
        technical=float(getattr(s,'technical_score',0) or 0)
        tier_rank=2 if g.get('tier')=='A_PLUS' else 1
        rank_key=(tier_rank, score, min(rr,5.0), technical, int(g.get('passed',0)))
        candidates.append((rank_key,s,g))
    candidates.sort(key=lambda x:x[0],reverse=True)
    return [(s,g) for _,s,g in candidates[:limit]]

def near_misses(evaluated,minimum,limit=5):
    """Return strongest early setups for monitoring; never treats them as trades."""
    rows=[]
    for s,g in evaluated:
        if not s or getattr(s,'direction','WAIT')=='WAIT': continue
        if g.get('tier') not in ('EARLY_SETUP',): continue
        rows.append(((float(g.get('score',getattr(s,'score',0)) or 0),float(getattr(s,'risk_reward',0) or 0)),s,g))
    rows.sort(key=lambda x:x[0],reverse=True)
    return [(s,g) for _,s,g in rows[:limit]]

def summary(results):
    counts={k:0 for k in ('QUALIFIED','EARLY_SETUP','REJECTED','INSUFFICIENT_DATA')}
    for r in results: counts[r.status]=counts.get(r.status,0)+1
    return counts
