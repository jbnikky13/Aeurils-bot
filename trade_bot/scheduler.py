import os
import asyncio
from telegram.ext import ContextTypes
from .live_setup import crypto_setup, stock_setup
from .discovered_signal import discovered_setup
from .formatter import format_signal
from .signal_lifecycle import record_open
from .paper_trader import open_paper_trade
from .discovery_pipeline import discovered_symbols
from .confluence_gate import evaluate
from .confluence_providers import crypto_evidence, stock_evidence

CHAT_ID=os.getenv("TELEGRAM_CHAT_ID")
MAX_DAILY_ACTIONABLE_SIGNALS=int(os.getenv("MAX_DAILY_ACTIONABLE_SIGNALS","3"))

def _entry(signal):
    if signal.entry_low is None or signal.entry_high is None: raise ValueError(f"{signal.symbol}: actionable signal has no entry range")
    return (float(signal.entry_low)+float(signal.entry_high))/2
async def _run_crypto(symbol):
    try:return await crypto_setup(symbol)
    except Exception:return None
async def _run_discovered(symbol):
    try:return await discovered_setup(symbol)
    except Exception:return None
def _run_stock(symbol):
    try:return stock_setup(symbol)
    except Exception:return None
async def _run_stock_async(symbol):return await asyncio.to_thread(_run_stock,symbol)
def _format_candidates(title,items):
    if not items:return f"{title}\nNo candidates met the filters."
    return "\n".join([title]+[f"• {x['symbol'].upper()} — {x['name']} | score {x['score']} | mcap ${x['market_cap']:,.0f} | 24h ${x['volume_24h']:,.0f} | 24h {x['price_change_24h']:.2f}% | 7d {x['price_change_7d']:.2f}%" for x in items])
def _format_rejected(items):
    if not items:return ""
    return "\n".join(["⚠️ DISCOVERY ELIGIBILITY"]+[f"• {x['symbol']}: {x['reason']}" for x in items[:8]])
def _gate_text(g):return f"Confluence: {g['passed']}/{g['minimum']} required\n"+"\n".join(f"✓ {x}" for x in g['confluences'])

async def daily_scan(context: ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID:raise RuntimeError("TELEGRAM_CHAT_ID is not configured")
    base_crypto=[x.strip().upper() for x in (os.getenv("WATCHLIST_CRYPTO") or "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if x.strip()]
    stocks=[x.strip().upper() for x in (os.getenv("WATCHLIST_STOCKS") or "NVDA,TSLA,AAPL,MSFT,AMZN").split(",") if x.strip()]
    discovered,trending,small_caps,rejected=await discovered_symbols(base_crypto)
    discovered_results=await asyncio.gather(*[_run_discovered(s) for s in discovered])
    crypto_results=await asyncio.gather(*[_run_crypto(s) for s in base_crypto])
    stock_results=await asyncio.gather(*[_run_stock_async(s) for s in stocks])
    signals=[s for s in [*discovered_results,*crypto_results,*stock_results] if s is not None]
    async def gated(s):
        is_crypto=s.symbol.upper().endswith('USDT')
        evidence=await crypto_evidence(s.symbol) if is_crypto else await asyncio.to_thread(stock_evidence,s)
        return s,evaluate(s,onchain=evidence if is_crypto else {},offchain=evidence if not is_crypto else {})
    evaluated=await asyncio.gather(*[gated(s) for s in signals])
    threshold=int(os.getenv("MIN_SIGNAL_SCORE","70"))
    candidates=[(s,g) for s,g in evaluated if s.direction!="WAIT" and s.score>=threshold and g['actionable']]
    candidates.sort(key=lambda x:(x[1]['passed'],float(x[0].score)),reverse=True)
    published=[];duplicates=[]
    for signal,gate in candidates[:MAX_DAILY_ACTIONABLE_SIGNALS]:
        sid,created=record_open(signal)
        if created:
            try:open_paper_trade(sid,signal.symbol,signal.direction,_entry(signal),signal.stop_loss,signal.take_profit_1,signal.take_profit_2)
            except Exception as exc:raise RuntimeError(f"Paper-trade ledger failed for {signal.symbol}: {exc}") from exc
            published.append((signal,sid,gate))
        else:duplicates.append(signal.symbol)
    if published:body="📊 AURELIS DAILY SIGNAL\n\n🟢 ACTIONABLE TRADE\n\n"+"\n\n".join(format_signal(s)+f"\nSignal ID: {sid}\nStatus: OPEN | PAPER TRADE ACTIVE\n{_gate_text(gate)}" for s,sid,gate in published)+f"\n\nDaily cap: {MAX_DAILY_ACTIONABLE_SIGNALS}"
    else:body="📊 AURELIS DAILY SIGNAL\n\n🟡 WATCH / WAIT\n\nNo crypto or stock setup passed the complete quality gate AND minimum 6-confluence requirement today.\nNo trade published."
    if duplicates:body+="\n\n🔁 Duplicate protection: "+", ".join(duplicates)+" suppressed."
    body+="\n\n"+_format_candidates("🔥 TRENDING WATCHLIST",trending)+"\n\n"+_format_candidates("💎 SMALL-CAP DISCOVERY",small_caps)
    rejected_text=_format_rejected(rejected)
    if rejected_text:body+="\n\n"+rejected_text
    body+="\n\nℹ️ Discovered assets are now analyzed with CoinGecko candles + DEX evidence when Binance symbols/contracts are unavailable. Missing wallet-level evidence remains UNKNOWN."
    for i in range(0,len(body),4000):await context.bot.send_message(chat_id=CHAT_ID,text=body[i:i+4000])
