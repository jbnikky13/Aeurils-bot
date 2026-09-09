import os,asyncio
from telegram.ext import ContextTypes
from .live_setup import crypto_setup
from .formatter import format_signal
from .signal_lifecycle import record_open
from .paper_trader import open_paper_trade
from .confluence_gate import evaluate
from .confluence_providers import crypto_evidence
from .binance_universe import all_binance_usdt_spot_symbols

CHAT_ID=os.getenv('TELEGRAM_CHAT_ID')
MAX_DAILY_ACTIONABLE_SIGNALS=int(os.getenv('MAX_DAILY_ACTIONABLE_SIGNALS','1'))
MAX_UNIVERSE_SCAN=int(os.getenv('MAX_UNIVERSE_SCAN','0'))
DAILY_FALLBACK_MIN_CONFLUENCES=int(os.getenv('DAILY_FALLBACK_MIN_CONFLUENCES','4'))
MARKET_DATA_CONCURRENCY=int(os.getenv('MARKET_DATA_CONCURRENCY','12'))
MAX_HOLD_HOURS=float(os.getenv('MAX_HOLD_HOURS','24'))

def _entry(signal):
    if signal.entry_low is None or signal.entry_high is None: raise ValueError(f'{signal.symbol}: actionable signal has no entry range')
    return (float(signal.entry_low)+float(signal.entry_high))/2

def _within_horizon(signal):
    """Only publish trades whose estimated TP1 is inside the swing horizon."""
    return getattr(signal,'horizon_status','UNKNOWN') == 'WITHIN_24H' and float(getattr(signal,'tp1_eta_hours',999999) or 999999) <= MAX_HOLD_HOURS

async def _run_crypto(symbol,sem):
    async with sem:
        try:return await crypto_setup(symbol)
        except Exception:return None

def _fallback_candidates(evaluated,minimum):
    candidates=[(s,g) for kind,symbol,s,g in evaluated if s is not None and getattr(s,'direction','WAIT')!='WAIT' and _within_horizon(s) and g.get('passed',0)>=minimum]
    candidates.sort(key=lambda x:(int(x[1].get('passed',0)),float(getattr(x[0],'score',0) or 0),float(getattr(x[0],'risk_reward',0) or 0)),reverse=True)
    return candidates

async def daily_scan(context:ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID:raise RuntimeError('TELEGRAM_CHAT_ID is not configured')
    try:base_crypto=all_binance_usdt_spot_symbols()
    except Exception:
        await context.bot.send_message(chat_id=CHAT_ID,text='NO TRADE SETUP TODAY.\n\nAURELIS could not validate the Binance market universe.')
        return
    if MAX_UNIVERSE_SCAN>0:base_crypto=base_crypto[:MAX_UNIVERSE_SCAN]
    pairs=[('crypto',s) for s in base_crypto]
    sem=asyncio.Semaphore(max(1,MARKET_DATA_CONCURRENCY))
    raw=await asyncio.gather(*[_run_crypto(s,sem) for _,s in pairs])

    async def gated(kind,symbol,signal):
        minimum=int(os.getenv('MIN_CONFLUENCES','6'))
        if signal is None:return kind,symbol,None,{'passed':0,'minimum':minimum,'actionable':False,'confluences':[],'checks':[],'failed':['Setup generation failed'],'unknown':['Setup data unavailable']}
        if not _within_horizon(signal):
            return kind,symbol,signal,{'passed':0,'minimum':minimum,'actionable':False,'confluences':[],'checks':[],'failed':['TP1 estimated beyond 24h swing horizon'],'unknown':[],'horizon_rejected':True}
        try:
            evidence=await crypto_evidence(symbol)
            gate=evaluate(signal,onchain=evidence,offchain={})
            return kind,symbol,signal,gate
        except Exception as exc:
            return kind,symbol,signal,{'passed':0,'minimum':minimum,'actionable':False,'confluences':[],'checks':[],'failed':[f'Confluence provider error: {type(exc).__name__}'],'unknown':['Evidence unavailable']}

    evaluated=await asyncio.gather(*[gated(kind,symbol,signal) for (kind,symbol),signal in zip(pairs,raw)])
    minimum=int(os.getenv('MIN_CONFLUENCES','6'))
    candidates=[(s,g) for kind,symbol,s,g in evaluated if s is not None and _within_horizon(s) and g.get('actionable') and g.get('passed',0)>=minimum]
    candidates.sort(key=lambda x:(float(getattr(x[0],'score',0) or 0),int(x[1].get('passed',0)),float(getattr(x[0],'risk_reward',0) or 0)),reverse=True)
    candidates=candidates[:MAX_DAILY_ACTIONABLE_SIGNALS]
    if not candidates:candidates=_fallback_candidates(evaluated,DAILY_FALLBACK_MIN_CONFLUENCES)[:MAX_DAILY_ACTIONABLE_SIGNALS]

    published=[]
    for signal,gate in candidates:
        sid,created=record_open(signal)
        if created:
            open_paper_trade(sid,signal.symbol,signal.direction,_entry(signal),signal.stop_loss,signal.take_profit_1,signal.take_profit_2,
                              final_score=signal.score,market_regime=getattr(signal,'market_regime','UNKNOWN'),
                              gemini_decision=getattr(signal,'gemini_decision',None),gemini_confidence=getattr(signal,'gemini_confidence',None),
                              gemini_available=1 if getattr(signal,'gemini_decision',None) not in (None,'UNAVAILABLE') else 0)
            published.append(signal)

    extended=[]
    for kind,symbol,signal,gate in evaluated:
        if signal is not None and getattr(signal,'direction','WAIT')!='WAIT' and not _within_horizon(signal):
            eta=getattr(signal,'tp1_eta_hours',None)
            extended.append(f"• {symbol}: TP1 ETA ~{eta:.1f}h — exceeds {MAX_HOLD_HOURS:.0f}h swing horizon" if eta is not None else f"• {symbol}: TP1 ETA >{MAX_HOLD_HOURS:.0f}h — extended setup")

    body='\n\n'.join(format_signal(s) for s in published) if published else 'NO TRADE SETUP TODAY.\n\nAURELIS found no valid Binance-listed setup inside the 24h swing horizon.'
    if extended:
        body += '\n\n⚠️ EXTENDED SETUPS (WATCH ONLY)\n' + '\n'.join(extended[:10])
    await context.bot.send_message(chat_id=CHAT_ID,text=body[:3900])
