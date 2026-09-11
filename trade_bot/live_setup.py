import os
from .market_data import crypto_klines, stock_daily
from .indicators import score as technical_score, enrich, strategy_context
from .signal_engine import build_setup
from .stock_sentiment import score as stock_sentiment
from .gemini_signal import confirm
from .market_regime import classify_regime


def _regime(df):
    r=enrich(df).iloc[-1]
    return classify_regime({'close':r.close,'ema20':r.ema20,'ema50':r.ema50,'ema200':r.ema200,'atr':r.atr})


def _entry_context(df):
    x=enrich(df).dropna(subset=['ema20','atr']); r=x.iloc[-1]; recent=x.tail(5)
    return float(r.ema20),float(recent.high.max()),float(recent.low.min()),float(r.rsi)


def _confirm_1h(symbol, direction):
    """Confirm a 4H direction with completed 1H structure before publishing."""
    try:
        df=crypto_klines(symbol,interval='1h',limit=240)
        if len(df)>=3: df=df.iloc[:-1].copy()
        score,bias,_,reasons=technical_score(df); ctx=strategy_context(df)
        adx=ctx.get('adx',0); plus=ctx.get('plus_di',0); minus=ctx.get('minus_di',0); rsi=ctx.get('rsi',50)
        if direction=='LONG':
            aligned=bias>=0.20 and plus>=minus
            healthy=adx>=18 and rsi<70
        elif direction=='SHORT':
            aligned=bias<=-0.20 and minus>=plus
            healthy=adx>=18 and rsi>30
        else: return False, score, bias, ['No directional setup']
        return bool(aligned and healthy),score,bias,reasons+[f'1H ADX {adx:.1f}',f'1H RSI {rsi:.1f}']
    except Exception as exc:
        return False,0,0,[f'1H confirmation unavailable: {type(exc).__name__}']


async def crypto_setup(symbol: str):
    """Generate from a completed 4H candle and validate with completed 1H structure."""
    df=crypto_klines(symbol,interval='4h',limit=240)
    signal_df=df.iloc[:-1].copy() if len(df)>=3 else df.copy()
    tech,tbias,atr,reasons=technical_score(signal_df); regime=_regime(signal_df); price=float(signal_df.iloc[-1].close)
    ema20,recent_high,recent_low,rsi=_entry_context(signal_df)
    preliminary=build_setup(symbol,'crypto',price,tech,50,50,tbias,0.0,atr,regime,ema20=ema20,recent_high=recent_high,recent_low=recent_low,rsi=rsi)
    if preliminary.direction in ('LONG','SHORT'):
        ok,one_h_score,one_h_bias,one_h_reasons=_confirm_1h(symbol,preliminary.direction)
        preliminary.reasons += [f'1H confirmation score: {one_h_score}/100',*one_h_reasons]
        if not ok:
            preliminary.direction='WAIT'; preliminary.entry_status='NO_1H_CONFIRMATION'; preliminary.entry_quality=None
            preliminary.entry_low=preliminary.entry_high=preliminary.stop_loss=preliminary.take_profit_1=preliminary.take_profit_2=preliminary.risk_reward=None
            preliminary.reasons.append('Trade rejected: 1H structure does not confirm the 4H direction.')
            preliminary.invalidation='Wait for 1H trend/momentum alignment or a clean retest.'
    ai=confirm(symbol,tech,tbias,50,0.0,price,atr)
    preliminary.gemini_confidence=ai.get('confidence'); preliminary.gemini_decision=ai.get('decision'); preliminary.gemini_rationale=ai.get('rationale','')
    ai_state='AVAILABLE' if ai.get('available') else 'UNAVAILABLE'; ai_conf=f"{float(ai['confidence']):.0f}/100" if ai.get('confidence') is not None else 'not scored'
    preliminary.reasons += ['Signal timeframe: 4h closed candle',f'Market regime: {regime}',f'Entry status: {preliminary.entry_status}'+(f' ({preliminary.entry_quality:.0f}/100)' if preliminary.entry_quality is not None else ''),f'Gemini confirmation: {ai.get("decision","UNAVAILABLE")} ({ai_conf}; {ai_state})',ai.get('rationale','')]
    return preliminary


def stock_setup(symbol: str):
    df=stock_daily(symbol); tech,tbias,atr,reasons=technical_score(df)
    try: sentiment,sr=stock_sentiment(symbol)
    except Exception as exc: sentiment,sr=50,[f'stock sentiment unavailable: {type(exc).__name__}']
    regime=_regime(df); price=float(df.iloc[-1].close); ema20,recent_high,recent_low,rsi=_entry_context(df)
    s=build_setup(symbol,'stock',price,tech,50,sentiment,tbias,0.0,atr,regime,ema20=ema20,recent_high=recent_high,recent_low=recent_low,rsi=rsi)
    s.reasons=reasons+sr+[f'Market regime: {regime}',f'Entry status: {s.entry_status}'+(f' ({s.entry_quality:.0f}/100)' if s.entry_quality is not None else '')]
    return s
