"""Independent confluence gate for daily signals.
No provider is treated as a positive confirmation when data is unavailable.
"""
import os
MIN_CONFLUENCES=int(os.getenv('MIN_CONFLUENCES','6'))

def evaluate(signal, onchain=None, offchain=None):
    s=signal
    checks=[]
    checks.append(('trend_structure', bool(getattr(s,'score',0)>=60), 'Trend/structure score'))
    checks.append(('direction', getattr(s,'direction','WAIT')!='WAIT', 'Directional setup'))
    checks.append(('entry_range', getattr(s,'entry_low',None) is not None and getattr(s,'entry_high',None) is not None, 'Defined entry range'))
    checks.append(('risk_reward', bool(getattr(s,'take_profit_1',None) is not None and getattr(s,'stop_loss',None) is not None), 'Defined risk/reward'))
    if offchain:
        for k,v,d in offchain.items(): checks.append((k,bool(v),d))
    if onchain:
        for k,v,d in onchain.items(): checks.append((k,bool(v),d))
    passed=[x for x in checks if x[1]]
    return {'passed':len(passed),'minimum':MIN_CONFLUENCES,'actionable':len(passed)>=MIN_CONFLUENCES,'confluences':[x[2] for x in passed],'checks':checks}
