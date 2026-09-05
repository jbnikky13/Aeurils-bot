import os
import asyncio
from telegram.ext import ContextTypes
from .live_setup import crypto_setup, stock_setup
from .formatter import format_signal
from .signal_lifecycle import record_open
from .paper_trader import open_paper_trade
from .gem_finder import discover_gems, discover_small_caps
from .gem_score import scan_candidates
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
def _run_stock(symbol):
    try:return stock_setup(symbol)
    except Exception:return None

def _format_candidates(title,items):
    if not items:return f"{title}\nNo candidates met the filters."
    return "\n".join([title]+[f"• {x['symbol'].upper()} — {x['name']} | score {x['score']} | mcap ${x['market_cap']:,.0f} | 24h ${x['volume_24h']:,.0f} | 24h {x['price_change_24h']:.2f}% | 7d {x['price_change_7d']:.2f}%" for x in items])
def _format_validated_gems(items):
    if not items:return "💎 VALIDATED GEM WATCHLIST\nNo candidates passed deeper validation."
    return "\n".join(["💎 VALIDATED GEM WATCHLIST"]+[f"• {x.symbol} — {x.name} | {x.status} | Gem {x.final_score:.1f}/100 | {'; '.join(str(r) for r in (x.reasons or [])[:3])}" for x in items])+"\n⚠️ WATCH is research/watchlist status, not an automatic buy signal."
def _gate_text(g):return f"Confluence: {g['passed']}/{g['minimum']} required\n"+"\n".join(f"✓ {x}" for x in g['confluences'])

async def daily_scan(context: ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID:raise RuntimeError("TELEGRAM_CHAT_ID is not configured")
    symbols=[x.strip().upper() for x in (os.getenv("WATCHLIST_CRYPTO") or "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if x.strip()]
    stocks=[x.strip().upper() for x in (os.getenv("WATCHLIST_STOCKS") or "NVDA,TSLA,AAPL,MSFT,AMZN").split(",") if x.strip()]
    crypto_results=await asyncio.gather(*[_run_crypto(s) for s in symbols]); stock_results=[await _run_stock(s) for s in stocks]
    signals=[s for s in [*crypto_results,*stock_results] if s is not None]
    async def gated(s):
        evidence=await crypto_evidence(s.symbol) if s.symbol.upper().endswith('USDT') else stock_evidence(s)
        return s,evaluate(s,onchain=evidence if s.symbol.upper().endswith('USDT') else {},offchain=evidence if not s.symbol.upper().endswith('USDT') else {})
    evaluated=await asyncio.gather(*[gated(s) for s in signals])
    threshold=int(os.getenv("MIN_SIGNAL_SCORE","70")); candidates=[(s,g) for s,g in evaluated if s.direction!="WAIT" and s.score>=threshold and g['actionable']]
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
    trending=discover_gems(limit=int(os.getenv("GEM_DISCOVERY_LIMIT","5")));small_caps=discover_small_caps(limit=int(os.getenv("SMALL_CAP_DISCOVERY_LIMIT","5")),max_market_cap=int(os.getenv("SMALL_CAP_MAX_MARKET_CAP","1000000000")))
    try:validated=await scan_candidates(limit=int(os.getenv("GEM_VALIDATION_LIMIT","5")))
    except Exception:validated=[]
    body+="\n\n"+_format_candidates("🔥 TRENDING WATCHLIST",trending)+"\n\n"+_format_candidates("💎 SMALL-CAP DISCOVERY",small_caps)+"\n\n"+_format_validated_gems([x for x in validated if x.status=="WATCH"][:int(os.getenv("GEM_VALIDATED_OUTPUT_LIMIT","5"))])
    for i in range(0,len(body),4000):await context.bot.send_message(chat_id=CHAT_ID,text=body[i:i+4000])
