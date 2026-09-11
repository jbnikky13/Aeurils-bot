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
MAX_DAILY_ACTIONABLE_SIGNALS=int(os.getenv('MAX_DAILY_ACTIONABLE_SIGNALS','5'))
MAX_UNIVERSE_SCAN=int(os.getenv('MAX_UNIVERSE_SCAN','0'))
DAILY_FALLBACK_MIN_CONFLUENCES=int(os.getenv('DAILY_FALLBACK_MIN_CONFLUENCES','4'))
MARKET_DATA_CONCURRENCY=int(os.getenv('MARKET_DATA_CONCURRENCY','12'))
MAX_HOLD_HOURS=float(os.getenv('MAX_HOLD_HOURS','24'))

def _entry(signal):
    if signal.entry_low is None or signal.entry_high is None: raise ValueError(f'{signal.symbol}: actionable signal has no entry range')
    return (float(signal.entry_low)+float(signal.entry_high))/2

def _horizon_status(signal):
    eta=getattr(signal,'tp1_eta_hours',None)
    if eta is None:return 'UNKNOWN'
    return 'WITHIN_24H' if float(eta)<=MAX_HOLD_HOURS else 'OVER_24H'

def _within_horizon(signal):
    return _horizon_status(signal)=='WITHIN_24H'

async def _run_crypto(symbol,sem):
    async with sem:
        try:return await crypto_setup(symbol)
        except Exception:return None

def _fallback_candidates(evaluated,minimum):
    candidates=[(s,g) for kind,symbol,s,g in evaluated if s is not None and getattr(s,'direction','WAIT')!='WAIT' and _within_horizon(s) and g.get('passed',0)>=minimum]
    candidates.sort(key=lambda x:(int(x[1].get('passed',0)),float(getattr(x[0],'score',0) or 0),float(getattr(x[0],'risk_reward',0) or 0)),reverse=True)
    return candidates

def _reason_counts(evaluated):
    counts={}
    for _,symbol,signal,gate in evaluated:
        if signal is None:
            reason='setup_generation_failed'
        elif getattr(signal,'direction','WAIT')=='WAIT':
            reason=getattr(signal,'reason',None) or getattr(signal,'status',None) or 'direction_wait'
        elif not gate.get('actionable'):
            failed=gate.get('failed') or gate.get('unknown') or ['confluence_gate_rejected']
            reason=str(failed[0])
        else:
            continue
        reason=' '.join(reason.replace('\n',' ').split())[:80]
        counts[reason]=counts.get(reason,0)+1
    return sorted(counts.items(),key=lambda x:x[1],reverse=True)[:5]

async def daily_scan(context:ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID:raise RuntimeError('TELEGRAM_CHAT_ID is not configured')
    try:base_crypto=all_binance_usdt_spot_symbols()
    except Exception:
        await context.bot.send_message(chat_id=CHAT_ID,text='🔴 AURELIS SCAN FAILED\n\nStage: Binance market universe\nReason: Could not validate Binance-listed symbols.')
        raise
    if MAX_UNIVERSE_SCAN>0:base_crypto=base_crypto[:MAX_UNIVERSE_SCAN]
    pairs=[('crypto',s) for s in base_crypto]
    sem=asyncio.Semaphore(max(1,MARKET_DATA_CONCURRENCY))
    raw=await asyncio.gather(*[_run_crypto(s,sem) for _,s in pairs])

    async def gated(kind,symbol,signal):
        minimum=int(os.getenv('MIN_CONFLUENCES','6'))
        if signal is None:return kind,symbol,None,{'passed':0,'minimum':minimum,'actionable':False,'confluences':[],'checks':[],'failed':['Setup generation failed'],'unknown':['Setup data unavailable']}
        try:
            evidence=await crypto_evidence(symbol)
            gate=evaluate(signal,onchain=evidence,offchain={})
            return kind,symbol,signal,gate
        except Exception as exc:
            return kind,symbol,signal,{'passed':0,'minimum':minimum,'actionable':False,'confluences':[],'checks':[],'failed':[f'Confluence provider error: {type(exc).__name__}'],'unknown':['Evidence unavailable']}

    evaluated=await asyncio.gather(*[gated(kind,symbol,signal) for (kind,symbol),signal in zip(pairs,raw)])
    minimum=int(os.getenv('MIN_CONFLUENCES','6'))
    technical_candidates=[(s,g) for kind,symbol,s,g in evaluated if s is not None and getattr(s,'direction','WAIT')!='WAIT']
    gated_candidates=[(s,g) for s,g in technical_candidates if g.get('actionable') and g.get('passed',0)>=minimum]
    candidates=[x for x in gated_candidates if _within_horizon(x[0])]
    candidates.sort(key=lambda x:(float(getattr(x[0],'score',0) or 0),int(x[1].get('passed',0)),float(getattr(x[0],'risk_reward',0) or 0)),reverse=True)

    # Publish the strongest setups up to the configured daily target. If the
    # primary gate leaves fewer than the target, fill from the softer fallback
    # pool rather than allowing a single arbitrary setup to be published.
    target=max(1,MAX_DAILY_ACTIONABLE_SIGNALS)
    selected=candidates[:target]
    if len(selected)<target:
        seen={getattr(s,'symbol',None) for s,_ in selected}
        for item in _fallback_candidates(evaluated,DAILY_FALLBACK_MIN_CONFLUENCES):
            symbol=getattr(item[0],'symbol',None)
            if symbol in seen:continue
            selected.append(item)
            seen.add(symbol)
            if len(selected)>=target:break
    candidates=selected

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
        if signal is not None and getattr(signal,'direction','WAIT')!='WAIT' and _horizon_status(signal)=='OVER_24H':
            eta=getattr(signal,'tp1_eta_hours',None)
            extended.append(f"• {symbol}: TP1 estimated ~{eta:.1f}h — requires more than 24h" if eta is not None else f"• {symbol}: TP1 estimated >{MAX_HOLD_HOURS:.0f}h — requires more than 24h")

    body='\n\n'.join(format_signal(s) for s in published) if published else 'NO TRADE SETUP TODAY.\n\nAURELIS found no valid Binance-listed setup.'
    if extended:
        body += '\n\n⚠️ EXTENDED SWING SETUPS\n' + '\n'.join(extended[:10])

    reasons=_reason_counts(evaluated)
    reason_text='\n'.join(f'• {reason}: {count}' for reason,count in reasons) or '• No rejection reasons recorded'
    diagnostics=(
        f"\n\n📊 AURELIS SCAN AUDIT\n"
        f"Universe: {len(base_crypto)} Binance USDT spot pairs\n"
        f"Technical candidates: {len(technical_candidates)}\n"
        f"Confluence-qualified: {len(gated_candidates)}\n"
        f"Within 24h: {len([x for x in gated_candidates if _within_horizon(x[0])])}\n"
        f"Published: {len(published)}\n\n"
        f"Top rejection reasons:\n{reason_text}"
    )
    await context.bot.send_message(chat_id=CHAT_ID,text=(body+diagnostics)[:3900])
