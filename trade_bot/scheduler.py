import os,asyncio
from telegram.ext import ContextTypes
from .live_setup import crypto_setup,stock_setup
from .formatter import format_signal
from .signal_lifecycle import record_open
from .paper_trader import open_paper_trade
from .confluence_gate import evaluate
from .confluence_providers import crypto_evidence,stock_evidence
from .binance_universe import all_binance_usdt_spot_symbols
from .binance_signal_audit import classify,summary,rank
CHAT_ID=os.getenv('TELEGRAM_CHAT_ID')
MAX_DAILY_ACTIONABLE_SIGNALS=int(os.getenv('MAX_DAILY_ACTIONABLE_SIGNALS','3'))
MAX_UNIVERSE_SCAN=int(os.getenv('MAX_UNIVERSE_SCAN','0'))

def _entry(signal):
    if signal.entry_low is None or signal.entry_high is None: raise ValueError(f'{signal.symbol}: actionable signal has no entry range')
    return (float(signal.entry_low)+float(signal.entry_high))/2
async def _run_crypto(symbol):
    try:return await crypto_setup(symbol)
    except Exception:return None
def _run_stock(symbol):
    try:return stock_setup(symbol)
    except Exception:return None
async def _run_stock_async(symbol):return await asyncio.to_thread(_run_stock,symbol)
def _gate_text(g):return f"Confluence: {g['passed']}/{g['minimum']} required\n"+'\n'.join(f"✓ {x}" for x in g['confluences'])
async def daily_scan(context:ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID:raise RuntimeError('TELEGRAM_CHAT_ID is not configured')
    try:base_crypto=all_binance_usdt_spot_symbols()
    except Exception:base_crypto=[x.strip().upper() for x in (os.getenv('WATCHLIST_CRYPTO') or 'BTCUSDT,ETHUSDT,SOLUSDT').split(',') if x.strip()]
    if MAX_UNIVERSE_SCAN>0:base_crypto=base_crypto[:MAX_UNIVERSE_SCAN]
    stocks=[x.strip().upper() for x in (os.getenv('WATCHLIST_STOCKS') or 'NVDA,TSLA,AAPL,MSFT,AMZN').split(',') if x.strip()]
    pairs=[('crypto',s) for s in base_crypto]+[('stock',s) for s in stocks]
    raw=await asyncio.gather(*[_run_crypto(s) if kind=='crypto' else _run_stock_async(s) for kind,s in pairs])
    signals=[]
    for (kind,symbol),signal in zip(pairs,raw):
        if signal is not None: signals.append((kind,symbol,signal))
    async def gated(item):
        kind,symbol,s=item
        evidence=await crypto_evidence(symbol) if kind=='crypto' else await asyncio.to_thread(stock_evidence,s)
        return kind,symbol,s,evaluate(s,onchain=evidence if kind=='crypto' else {},offchain=evidence if kind=='stock' else {})
    evaluated=await asyncio.gather(*[gated(x) for x in signals])
    minimum=int(os.getenv('MIN_CONFLUENCES','6'))
    audit=[classify(symbol,s,g,minimum) for kind,symbol,s,g in evaluated]
    candidates=rank([(s,g) for kind,symbol,s,g in evaluated],minimum,MAX_DAILY_ACTIONABLE_SIGNALS)
    published=[];duplicates=[]
    for signal,gate in candidates:
        sid,created=record_open(signal)
        if created:
            open_paper_trade(sid,signal.symbol,signal.direction,_entry(signal),signal.stop_loss,signal.take_profit_1,signal.take_profit_2)
            published.append((signal,sid,gate))
        else:duplicates.append(signal.symbol)
    if published:
        body='📊 AURELIS DAILY SIGNAL\n\n🟢 ACTIONABLE TRADE SETUPS\n\n'+'\n\n'.join(format_signal(s)+f'\nSignal ID: {sid}\nStatus: OPEN | PAPER TRADE ACTIVE\n{_gate_text(gate)}' for s,sid,gate in published)+f'\n\nDaily cap: {MAX_DAILY_ACTIONABLE_SIGNALS}'
    else:
        counts=summary(audit)
        body=f"📊 AURELIS DAILY SIGNAL\n\n🟡 WATCH / WAIT\n\nNo Binance crypto or configured stock setup passed the complete quality gate AND minimum {minimum}-confluence requirement today.\nNo trade published.\n\n📋 SCAN AUDIT\n✓ Qualified: {counts['QUALIFIED']}\n✕ Rejected: {counts['REJECTED']}\n? Insufficient data: {counts['INSUFFICIENT_DATA']}"
    if duplicates:body+='\n\n🔁 Duplicate protection: '+', '.join(duplicates)+' suppressed.'
    body+=f'\n\n🎯 CORE UNIVERSE: {len(base_crypto)} Binance USDT spot pairs + {len(stocks)} configured stocks.\nDiscovery feature: DISABLED.'
    for i in range(0,len(body),4000):await context.bot.send_message(chat_id=CHAT_ID,text=body[i:i+4000])
