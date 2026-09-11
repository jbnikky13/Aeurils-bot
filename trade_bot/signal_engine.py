from dataclasses import dataclass
from typing import Literal

Direction = Literal['LONG','SHORT','WAIT']
MAX_HOLD_HOURS=24.0
# Strategy 3.0: selective, but intentionally not over-filtered.
MAX_ENTRY_EXTENSION_ATR=0.90
OVERBOUGHT_RSI=75.0
OVERSOLD_RSI=25.0
MIN_SETUP_SCORE=58

@dataclass
class Signal:
    symbol:str; asset_type:str; direction:Direction; score:int; entry_low:float|None; entry_high:float|None; stop_loss:float|None; take_profit_1:float|None; take_profit_2:float|None; risk_reward:float|None; technical_score:int; whale_score:int; sentiment_score:float; reasons:list[str]; invalidation:str; market_regime:str='UNKNOWN'; gemini_confidence:float|None=None; gemini_decision:str|None=None; gemini_rationale:str|None=None; whale_bias:float|None=None; tp1_eta_hours:float|None=None; tp2_eta_hours:float|None=None; horizon_status:str='UNKNOWN'; max_hold_hours:float=MAX_HOLD_HOURS; entry_status:str='UNKNOWN'; entry_quality:float|None=None

def combine_scores(technical:float,whale:float,sentiment:float)->int:return max(0,min(100,round(.55*technical+.30*whale+.15*sentiment)))
def direction_from_components(technical_bias:float,whale_bias:float)->Direction:
    # Technical direction leads; flow can support or modestly oppose it without vetoing ordinary setups.
    bias=.70*technical_bias+.30*whale_bias
    if bias>=.15:return 'LONG'
    if bias<=-.15:return 'SHORT'
    return 'WAIT'
def _eta_hours(distance:float,atr:float,asset_type:str)->float|None:
    if distance<=0 or atr<=0:return None
    return distance/atr if asset_type=='crypto' else (distance/atr)*24.0

def build_setup(symbol:str,asset_type:str,price:float,technical_score:int,whale_score:int,sentiment_score:float,technical_bias:float,whale_bias:float,atr:float,market_regime:str='UNKNOWN',ema20:float|None=None,recent_high:float|None=None,recent_low:float|None=None,rsi:float|None=None)->Signal:
    direction=direction_from_components(technical_bias,whale_bias); score=combine_scores(technical_score,whale_score,sentiment_score)
    if direction=='WAIT' or score<MIN_SETUP_SCORE or atr<=0:return Signal(symbol,asset_type,'WAIT',score,None,None,None,None,None,None,technical_score,whale_score,sentiment_score,['No sufficiently strong directional setup.'],'Wait for confirmation.',market_regime,whale_bias=whale_bias)
    entry_anchor=float(ema20) if ema20 is not None else float(price); extension_atr=abs(price-entry_anchor)/atr; entry_quality=max(0,100-(extension_atr/MAX_ENTRY_EXTENSION_ATR)*100)
    if ema20 is not None and extension_atr>MAX_ENTRY_EXTENSION_ATR:return Signal(symbol,asset_type,'WAIT',score,None,None,None,None,None,None,technical_score,whale_score,sentiment_score,[f'Entry rejected: price is {extension_atr:.2f} ATR from EMA20; avoid chasing.'],'Wait for a pullback/retest toward the EMA20 entry area.',market_regime,whale_bias=whale_bias,entry_status='EXTENDED',entry_quality=entry_quality)
    if rsi is not None:
        if direction=='LONG' and rsi>OVERBOUGHT_RSI:return Signal(symbol,asset_type,'WAIT',score,None,None,None,None,None,None,technical_score,whale_score,sentiment_score,[f'Entry rejected: RSI {rsi:.1f} is extremely overbought for a new long.'],'Wait for RSI to cool and price to retest support.',market_regime,whale_bias=whale_bias,entry_status='OVEREXTENDED_MOMENTUM',entry_quality=entry_quality)
        if direction=='SHORT' and rsi<OVERSOLD_RSI:return Signal(symbol,asset_type,'WAIT',score,None,None,None,None,None,None,technical_score,whale_score,sentiment_score,[f'Entry rejected: RSI {rsi:.1f} is extremely oversold for a new short.'],'Wait for RSI to recover and price to retest resistance.',market_regime,whale_bias=whale_bias,entry_status='OVEREXTENDED_MOMENTUM',entry_quality=entry_quality)
    zone=min(.0035,max(.00075,.15*atr/price)); entry_low,entry_high=price*(1-zone),price*(1+zone)
    if direction=='LONG':stop,tp1,tp2=price-1.5*atr,price+2*atr,price+3*atr
    else:stop,tp1,tp2=price+1.5*atr,price-2*atr,price-3*atr
    # Structure is a warning unless it leaves genuinely little room for TP1.
    if direction=='LONG' and recent_high is not None and recent_high>price and recent_high<tp1 and (recent_high-price)<.50*atr:
        return Signal(symbol,asset_type,'WAIT',score,None,None,None,None,None,None,technical_score,whale_score,sentiment_score,[f'Entry rejected: nearby resistance at {recent_high:.6g} leaves very little room for TP1.'],'Wait for a clean breakout/retest of resistance.',market_regime,whale_bias=whale_bias,entry_status='BLOCKED_BY_RESISTANCE',entry_quality=entry_quality)
    if direction=='SHORT' and recent_low is not None and recent_low<price and recent_low>tp1 and (price-recent_low)<.50*atr:
        return Signal(symbol,asset_type,'WAIT',score,None,None,None,None,None,None,technical_score,whale_score,sentiment_score,[f'Entry rejected: nearby support at {recent_low:.6g} leaves very little room for TP1.'],'Wait for a clean breakdown/retest of support.',market_regime,whale_bias=whale_bias,entry_status='BLOCKED_BY_SUPPORT',entry_quality=entry_quality)
    risk=abs(price-stop); reward=abs(tp2-price); tp1_eta=_eta_hours(abs(tp1-price),atr,asset_type); tp2_eta=_eta_hours(abs(tp2-price),atr,asset_type); horizon_status='WITHIN_24H' if tp1_eta is not None and tp1_eta<=MAX_HOLD_HOURS else 'OVER_24H'
    reasons=[f'Technical score: {technical_score}/100',f'Whale-flow score: {whale_score}/100',f'Sentiment score: {sentiment_score}/100',f'Market regime: {market_regime}',f'Entry quality: {entry_quality:.0f}/100 ({extension_atr:.2f} ATR from EMA20)' if ema20 is not None else 'Entry quality: current-price zone',f'Estimated TP1: {tp1_eta:.1f}h' if tp1_eta is not None else 'Estimated TP1: unavailable',f'Estimated TP2: {tp2_eta:.1f}h' if tp2_eta is not None else 'Estimated TP2: unavailable','TP1 horizon: within 24h' if horizon_status=='WITHIN_24H' else '⚠️ TP1 horizon exceeds 24h — extended setup']
    return Signal(symbol,asset_type,direction,score,entry_low,entry_high,stop,tp1,tp2,reward/risk if risk else None,technical_score,whale_score,sentiment_score,reasons,f'Invalid if price breaks the {direction.lower()} stop-loss level.',market_regime,whale_bias=whale_bias,tp1_eta_hours=tp1_eta,tp2_eta_hours=tp2_eta,horizon_status=horizon_status,entry_status='READY',entry_quality=entry_quality)
