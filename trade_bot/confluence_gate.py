"""Strict confluence gate used by the daily service.
Only evidence actually supplied by the signal/provider layer can pass.
Missing data is UNKNOWN and never counts as a confirmation.
"""
import os
MIN_CONFLUENCES=int(os.getenv('MIN_CONFLUENCES','6'))
OFFCHAIN_KEYS=('trend_structure','direction','entry_range','risk_reward','volume_liquidity','market_regime','sentiment_narrative','news_context')
ONCHAIN_KEYS=('onchain_dex_activity','buy_sell_pressure','liquidity_depth')

def evaluate(signal,onchain=None,offchain=None):
    checks=[
      ('trend_structure',bool(getattr(signal,'score',0)>=60),'Trend / market structure'),
      ('direction',getattr(signal,'direction','WAIT')!='WAIT','Directional setup'),
      ('entry_range',getattr(signal,'entry_low',None) is not None and getattr(signal,'entry_high',None) is not None,'Defined entry range'),
      ('risk_reward',getattr(signal,'take_profit_1',None) is not None and getattr(signal,'stop_loss',None) is not None,'Defined risk/reward'),
    ]
    for key,value in (offchain or {}).items():
        if key in OFFCHAIN_KEYS: checks.append((key,bool(value),key.replace('_',' ').title()))
    for key,value in (onchain or {}).items():
        if key in ONCHAIN_KEYS: checks.append((key,bool(value),key.replace('_',' ').title()))
    passed=[x for x in checks if x[1]]
    independent=[x for x in passed if x[0] in set(OFFCHAIN_KEYS+ONCHAIN_KEYS)]
    return {'passed':len(independent),'minimum':MIN_CONFLUENCES,'actionable':len(independent)>=MIN_CONFLUENCES and getattr(signal,'direction','WAIT')!='WAIT','confluences':[x[2] for x in independent],'checks':checks,'failed':[x[2] for x in checks if not x[1]],'unknown':[k.replace('_',' ').title() for k in (set(OFFCHAIN_KEYS+ONCHAIN_KEYS)-{x[0] for x in checks})]}
