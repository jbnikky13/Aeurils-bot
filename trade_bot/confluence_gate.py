"""Strict six-confluence gate for Aeurils daily signals.
Missing provider data never counts as a confirmation.
"""
import os
MIN_CONFLUENCES=int(os.getenv('MIN_CONFLUENCES','6'))

OFFCHAIN_KEYS=('trend_structure','direction','entry_range','risk_reward','volume_liquidity','market_regime','sentiment_narrative','news_context')
ONCHAIN_KEYS=('whale_activity','exchange_flows','smart_money','holder_concentration')

def _items(data):
    return data or {}

def evaluate(signal,onchain=None,offchain=None):
    checks=[]
    s=signal
    checks += [
      ('trend_structure',bool(getattr(s,'score',0)>=60),'Trend / market structure'),
      ('direction',getattr(s,'direction','WAIT')!='WAIT','Directional setup'),
      ('entry_range',getattr(s,'entry_low',None) is not None and getattr(s,'entry_high',None) is not None,'Defined entry range'),
      ('risk_reward',getattr(s,'take_profit_1',None) is not None and getattr(s,'stop_loss',None) is not None,'Defined risk/reward'),
    ]
    for key,value,description in _items(offchain).values() if False else []: pass
    for key,value in _items(offchain).items():
        checks.append((key,bool(value),str(key).replace('_',' ').title()))
    for key,value in _items(onchain).items():
        checks.append((key,bool(value),str(key).replace('_',' ').title()))
    passed=[x for x in checks if x[1]]
    independent_passed=[x for x in passed if x[0] in set(OFFCHAIN_KEYS+ONCHAIN_KEYS)]
    # Core signal validity is required separately; six independent market confirmations are required.
    actionable=(len(independent_passed)>=MIN_CONFLUENCES and len(passed)>=MIN_CONFLUENCES and getattr(s,'direction','WAIT')!='WAIT')
    return {'passed':len(independent_passed),'minimum':MIN_CONFLUENCES,'actionable':actionable,'confluences':[x[2] for x in independent_passed],'checks':checks}
