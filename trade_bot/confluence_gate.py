"""Strict six-confluence gate for Aeurils daily signals.
Core market/risk checks and supplied live evidence are counted separately.
Missing provider data is UNKNOWN and never counts as confirmation.
"""
import os
MIN_CONFLUENCES=int(os.getenv('MIN_CONFLUENCES','6'))
OFFCHAIN_KEYS=('trend_structure','direction','entry_range','risk_reward','volume_liquidity','market_regime','sentiment_narrative','news_context')
ONCHAIN_KEYS=('onchain_dex_activity','buy_sell_pressure','liquidity_depth','whale_activity','exchange_flows','smart_money','holder_concentration')

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
    return {'passed':len(passed),'minimum':MIN_CONFLUENCES,'actionable':len(passed)>=MIN_CONFLUENCES and getattr(signal,'direction','WAIT')!='WAIT','confluences':[x[2] for x in passed],'checks':checks,'failed':[x[2] for x in checks if not x[1]],'unknown':[k.replace('_',' ').title() for k in (set(OFFCHAIN_KEYS+ONCHAIN_KEYS)-{x[0] for x in checks})]}
