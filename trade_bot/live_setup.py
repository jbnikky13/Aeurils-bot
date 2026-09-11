import os
from .market_data import crypto_klines, stock_daily
from .indicators import score as technical_score, enrich, strategy_context
from .signal_engine import build_setup
from .stock_sentiment import score as stock_sentiment
from .gemini_signal import confirm
from .market_regime import classify_regime
from .binance_flow import snapshot as binance_flow


def _regime(df):
    r=enrich(df).iloc[-1]
    return classify_regime({'close':r.close,'ema20':r.ema20,'ema50':r.ema50,'ema200':r.ema200,'atr':r.atr})


def _entry_context(df):
    x=enrich(df).dropna(subset=['ema20','atr']); r=x.iloc[-1]; recent=x.tail(20)
    return float(r.ema20),float(recent.high.max()),float(recent.low.min()),float(r.rsi)


def _confirm_1h(symbol, direction):
    """Use 1H as confirmation, not a rigid all-indicators veto."""
    try:
        df=crypto_klines(symbol,interval='1h',limit=240)
        if len(df)>=3: df=df.iloc[:-1].copy()
        score,bias,_,reasons=technical_score(df); ctx=strategy_context(df)
        adx=ctx.get('adx',0); plus=ctx.get('plus_di',0); minus=ctx.get('minus_di',0); rsi=ctx.get('rsi',50)
        if direction=='LONG':
            aligned=bias>=0.10 and plus>=minus-0.05
            healthy=adx>=14 and rsi<75
        elif direction=='SHORT':
            aligned=bias<=-0.10 and minus>=plus-0.05
            healthy=adx>=14 and rsi>25
        else: return False, score, bias, ['No directional setup']
        # 1H disagreement is a soft warning; only clearly broken structure vetoes the setup.
        return bool(aligned and healthy),score,bias,reasons+[f'1H ADX {adx:.1f}',f'1H RSI {rsi:.1f}']
    except Exception as exc:
        # Don't create a trade solely because confirmation failed, but make the failure explicit.
        return False,0,0,[f'1H confirmation unavailable: {type(exc).__name__}']


def _flow_ok(direction, flow):
    """Binance flow is supporting evidence; only severe conflict vetoes a setup."""
    if not flow.get('available'):
        return True
    score=float(flow.get('score',50)); bias=float(flow.get('bias',0))
    if direction=='LONG':
        return not (score < 40 and bias < -0.45)
    if direction=='SHORT':
        return not (score < 40 and bias > 0.45)
    return False


async def crypto_setup(symbol: str):
    """Generate from a completed 4H candle, then use 1H structure and Binance flow as confirmation."""
    df=crypto_klines(symbol,interval='4h',limit=240)
    signal_df=df.iloc[:-1].copy() if len(df)>=3 else df.copy()
    tech,tbias,atr,reasons=technical_score(signal_df); regime=_regime(signal_df); price=float(signal_df.iloc[-1].close)
    ema20,recent_high,recent_low,rsi=_entry_context(signal_df)

    preliminary=build_setup(symbol,'crypto',price,tech,50,50,tbias,0.0,atr,regime,ema20=ema20,recent_high=recent_high,recent_low=recent_low,rsi=rsi)
    flow={'available':False,'score':50,'bias':0,'reasons':['Flow not queried because technical screen produced no trade candidate.']}
    if preliminary.direction in ('LONG','SHORT'):
        flow=binance_flow(symbol,preliminary.direction)
        flow_score=float(flow.get('score',50)); flow_bias=float(flow.get('bias',0))
        preliminary=build_setup(symbol,'crypto',price,tech,round(flow_score),50,tbias,flow_bias,atr,regime,ema20=ema20,recent_high=recent_high,recent_low=recent_low,rsi=rsi)
        preliminary.reasons += ['Binance market-flow confirmation:',*flow.get('reasons',[]),f'Flow score: {flow_score:.0f}/100',f'Flow bias: {flow_bias:+.2f}']
        if not _flow_ok(preliminary.direction,flow):
            preliminary.direction='WAIT'; preliminary.entry_status='FLOW_CONFLICT'; preliminary.entry_quality=None
            preliminary.entry_low=preliminary.entry_high=preliminary.stop_loss=preliminary.take_profit_1=preliminary.take_profit_2=preliminary.risk_reward=None
            preliminary.reasons.append('Trade rejected: Binance flow shows a severe conflict with the 4H setup.')
            preliminary.invalidation='Wait for market flow to align with the 4H direction.'

    if preliminary.direction in ('LONG','SHORT'):
        ok,one_h_score,one_h_bias,one_h_reasons=_confirm_1h(symbol,preliminary.direction)
        preliminary.reasons += [f'1H confirmation score: {one_h_score}/100',*one_h_reasons]
        if not ok:
            preliminary.direction='WAIT'; preliminary.entry_status='NO_1H_CONFIRMATION'; preliminary.entry_quality=None
            preliminary.entry_low=preliminary.entry_high=preliminary.stop_loss=preliminary.take_profit_1=preliminary.take_profit_2=preliminary.risk_reward=None
            preliminary.reasons.append('Trade rejected: 1H structure did not provide enough confirmation.')
            preliminary.invalidation='Wait for 1H trend/momentum alignment or a clean retest.'

    ai=confirm(symbol,tech,tbias,50,0.0,price,atr)
    preliminary.gemini_confidence=ai.get('confidence'); preliminary.gemini_decision=ai.get('decision'); preliminary.gemini_rationale=ai.get('rationale','')
    ai_state='AVAILABLE' if ai.get('available') else 'UNAVAILABLE'; ai_conf=f"{float(ai['confidence']):.0f}/100" if ai.get('confidence') is not None else 'not scored'
    preliminary.reasons += ['Signal timeframe: 4h closed candle','Execution/validation timeframe: 1h completed candles',f'Market regime: {regime}',f'Entry status: {preliminary.entry_status}'+(f' ({preliminary.entry_quality:.0f}/100)' if preliminary.entry_quality is not None else ''),f'Gemini confirmation: {ai.get("decision","UNAVAILABLE")} ({ai_conf}; {ai_state})',ai.get('rationale','')]
    return preliminary


def stock_setup(symbol: str):
    df=stock_daily(symbol); tech,tbias,atr,reasons=technical_score(df)
    try: sentiment,sr=stock_sentiment(symbol)
    except Exception as exc: sentiment,sr=50,[f'stock sentiment unavailable: {type(exc).__name__}']
    regime=_regime(df); price=float(df.iloc[-1].close); ema20,recent_high,recent_low,rsi=_entry_context(df)
    s=build_setup(symbol,'stock',price,tech,50,sentiment,tbias,0.0,atr,regime,ema20=ema20,recent_high=recent_high,recent_low=recent_low,rsi=rsi)
    s.reasons=reasons+sr+[f'Market regime: {regime}',f'Entry status: {s.entry_status}'+(f' ({s.entry_quality:.0f}/100)' if s.entry_quality is not None else '')]
    return s
