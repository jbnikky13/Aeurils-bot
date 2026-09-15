import os
from .market_data import crypto_klines, crypto_futures_klines, stock_daily
from .indicators import score as technical_score, enrich, strategy_context
from .signal_engine import build_setup, direction_from_components
from .stock_sentiment import score as stock_sentiment
from .gemini_signal import confirm
from .market_regime import classify_regime
from .binance_flow import snapshot as binance_flow
from .futures_engine import assess as assess_continuation


def _regime(df):
    r=enrich(df).iloc[-1]
    return classify_regime({'close':r.close,'ema20':r.ema20,'ema50':r.ema50,'ema200':r.ema200,'atr':r.atr})


def _entry_context(df):
    x=enrich(df).dropna(subset=['ema20','atr']); r=x.iloc[-1]; prior=x.iloc[:-1].tail(20)
    return float(r.ema20),float(prior.high.max()) if len(prior) else float(r.high),float(prior.low.min()) if len(prior) else float(r.low),float(r.rsi)


def _crypto_futures_candles(symbol, interval, limit=240):
    try: return crypto_futures_klines(symbol, interval=interval, limit=limit), 'FUTURES'
    except Exception: return crypto_klines(symbol, interval=interval, limit=limit), 'SPOT_FALLBACK'


def _confirm_1h(symbol, direction, continuation_mode=False):
    try:
        df,source=_crypto_futures_candles(symbol,'1h',240)
        if len(df)>=3: df=df.iloc[:-1].copy()
        score,bias,_,reasons=technical_score(df); ctx=strategy_context(df); adx=ctx.get('adx',0); plus=ctx.get('plus_di',0); minus=ctx.get('minus_di',0); rsi=ctx.get('rsi',50)
        if direction=='LONG': aligned=bias>=0.10 and plus>=minus-0.05; healthy=adx>=14 and (rsi<75 or continuation_mode)
        elif direction=='SHORT': aligned=bias<=-0.10 and minus>=plus-0.05; healthy=adx>=14 and (rsi>25 or continuation_mode)
        else: return False,score,bias,['No directional setup']
        return bool(aligned and healthy),score,bias,reasons+[f'1H ADX {adx:.1f}',f'1H RSI {rsi:.1f}',f'1H source: {source}']
    except Exception as exc: return False,0,0,[f'1H confirmation unavailable: {type(exc).__name__}']


def _flow_ok(direction,flow):
    if not flow.get('available'): return True
    score=float(flow.get('score',50)); bias=float(flow.get('bias',0))
    if direction=='LONG': return not (score<40 and bias<-0.45)
    if direction=='SHORT': return not (score<40 and bias>0.45)
    return False


async def crypto_setup(symbol: str):
    """Generate from completed 4H USD-M futures candles, then confirm on 1H."""
    df,source=_crypto_futures_candles(symbol,'4h',240); signal_df=df.iloc[:-1].copy() if len(df)>=3 else df.copy()
    tech,tbias,atr,reasons=technical_score(signal_df); regime=_regime(signal_df); price=float(signal_df.iloc[-1].close); ema20,recent_high,recent_low,rsi=_entry_context(signal_df)
    provisional=direction_from_components(tbias,0.0)
    flow={'available':False,'score':50,'bias':0,'reasons':['Futures flow not queried because no directional candidate was found.']}
    if provisional in ('LONG','SHORT'): flow=binance_flow(symbol,provisional)
    flow_score=float(flow.get('score',50)); flow_bias=float(flow.get('bias',0)); final_direction=direction_from_components(tbias,flow_bias)
    continuation=assess_continuation(enrich(signal_df),final_direction,flow) if final_direction in ('LONG','SHORT') else assess_continuation(enrich(signal_df),'WAIT',flow)
    final_mode=continuation.mode if continuation.mode in ('CONTINUATION','BREAKOUT') else 'NORMAL'
    preliminary=build_setup(symbol,'crypto',price,tech,round(flow_score),50,tbias,flow_bias,atr,regime,ema20=ema20,recent_high=recent_high,recent_low=recent_low,rsi=rsi,strategy_mode=final_mode,continuation_score=continuation.score)
    preliminary.reasons += [f'Crypto market source: {source}','Binance futures market-flow confirmation:',*flow.get('reasons',[]),f'Flow score: {flow_score:.0f}/100',f'Flow bias: {flow_bias:+.2f}','Futures continuation engine:',*continuation.reasons,f'Continuation score: {continuation.score}/100']

    if preliminary.direction in ('LONG','SHORT') and not _flow_ok(preliminary.direction,flow):
        preliminary.direction='WAIT'; preliminary.entry_status='FLOW_CONFLICT'; preliminary.entry_quality=None; preliminary.entry_low=preliminary.entry_high=preliminary.stop_loss=preliminary.take_profit_1=preliminary.take_profit_2=preliminary.risk_reward=None
        preliminary.reasons.append('Trade rejected: Binance futures flow shows a severe conflict with the 4H setup.'); preliminary.invalidation='Wait for futures flow to align with the 4H direction.'

    if preliminary.direction in ('LONG','SHORT'):
        ok,one_h_score,one_h_bias,one_h_reasons=_confirm_1h(symbol,preliminary.direction,preliminary.runner_enabled)
        preliminary.reasons += [f'1H confirmation score: {one_h_score}/100',*one_h_reasons]
        if not ok:
            preliminary.direction='WAIT'; preliminary.entry_status='NO_1H_CONFIRMATION'; preliminary.entry_quality=None; preliminary.entry_low=preliminary.entry_high=preliminary.stop_loss=preliminary.take_profit_1=preliminary.take_profit_2=preliminary.risk_reward=None
            preliminary.reasons.append('Trade rejected: 1H structure did not provide enough confirmation.'); preliminary.invalidation='Wait for 1H trend/momentum alignment or a clean retest.'

    ai=confirm(symbol,tech,tbias,flow_score,flow_bias,price,atr)
    preliminary.gemini_confidence=ai.get('confidence'); preliminary.gemini_decision=ai.get('decision'); preliminary.gemini_rationale=ai.get('rationale',''); ai_state='AVAILABLE' if ai.get('available') else 'UNAVAILABLE'; ai_conf=f"{float(ai['confidence']):.0f}/100" if ai.get('confidence') is not None else 'not scored'
    preliminary.reasons += ['Signal timeframe: 4h closed futures candle','Execution/validation timeframe: 1h completed futures candles',f'Market regime: {regime}',f'Strategy mode: {preliminary.strategy_mode}',f'Entry status: {preliminary.entry_status}'+(f' ({preliminary.entry_quality:.0f}/100)' if preliminary.entry_quality is not None else ''),f'Gemini confirmation: {ai.get("decision","UNAVAILABLE")} ({ai_conf}; {ai_state})',ai.get('rationale','')]
    return preliminary


def stock_setup(symbol: str):
    df=stock_daily(symbol); tech,tbias,atr,reasons=technical_score(df)
    try: sentiment,sr=stock_sentiment(symbol)
    except Exception as exc: sentiment,sr=50,[f'stock sentiment unavailable: {type(exc).__name__}']
    regime=_regime(df); price=float(df.iloc[-1].close); ema20,recent_high,recent_low,rsi=_entry_context(df)
    s=build_setup(symbol,'stock',price,tech,50,sentiment,tbias,0.0,atr,regime,ema20=ema20,recent_high=recent_high,recent_low=recent_low,rsi=rsi)
    s.reasons=reasons+sr+[f'Market regime: {regime}',f'Entry status: {s.entry_status}'+(f' ({s.entry_quality:.0f}/100)' if s.entry_quality is not None else '')]
    return s
