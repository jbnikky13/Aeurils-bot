import os
import asyncio
from telegram.ext import ContextTypes
from .live_setup import crypto_setup, stock_setup
from .formatter import format_signal
from .journal import record_setup
from .gem_finder import discover_gems, discover_small_caps
from .gem_score import scan_candidates

CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def _run_crypto(symbol):
    try: return await crypto_setup(symbol)
    except Exception: return None

def _run_stock(symbol):
    try: return stock_setup(symbol)
    except Exception: return None

def _format_candidates(title, items):
    if not items: return f"{title}\nNo candidates met the filters."
    lines=[title]
    for x in items:
        lines.append(f"• {x['symbol'].upper()} — {x['name']} | score {x['score']} | mcap ${x['market_cap']:,.0f} | 24h ${x['volume_24h']:,.0f} | 24h {x['price_change_24h']:.2f}% | 7d {x['price_change_7d']:.2f}%")
    return "\n".join(lines)

def _format_validated_gems(items):
    if not items: return "💎 VALIDATED GEM WATCHLIST\nNo candidates passed deeper validation."
    lines=["💎 VALIDATED GEM WATCHLIST"]
    for x in items:
        lines.append(f"• {x.symbol} — {x.name} | {x.status} | Gem {x.final_score:.1f}/100 | " + "; ".join(x.reasons[:3]))
    lines.append("⚠️ WATCH is research/watchlist status, not an automatic buy signal.")
    return "\n".join(lines)

async def daily_scan(context: ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID: raise RuntimeError("TELEGRAM_CHAT_ID is not configured")
    symbols=[x.strip().upper() for x in os.getenv("WATCHLIST_CRYPTO","BTCUSDT,ETHUSDT,SOLUSDT").split(",") if x.strip()]
    stocks=[x.strip().upper() for x in os.getenv("WATCHLIST_STOCKS","NVDA,TSLA,AAPL,MSFT,AMZN").split(",") if x.strip()]
    crypto_results=await asyncio.gather(*[_run_crypto(s) for s in symbols])
    stock_results=[_run_stock(s) for s in stocks]
    signals=[s for s in [*crypto_results,*stock_results] if s is not None]
    threshold=int(os.getenv("MIN_SIGNAL_SCORE","70"))
    publish=[s for s in signals if s.direction != "WAIT" and s.score >= threshold]
    for signal in publish: record_setup(signal)
    trending=discover_gems(limit=int(os.getenv("GEM_DISCOVERY_LIMIT","5")))
    small_caps=discover_small_caps(limit=int(os.getenv("SMALL_CAP_DISCOVERY_LIMIT","5")),max_market_cap=int(os.getenv("SMALL_CAP_MAX_MARKET_CAP","1000000000")))
    try:
        validated=await scan_candidates(limit=int(os.getenv("GEM_VALIDATION_LIMIT","5")))
    except Exception:
        validated=[]
    if publish:
        body="📊 AURELIS DAILY TRADE SETUPS\n\n"+"\n\n".join(format_signal(s) for s in publish)
    else:
        body="📊 AURELIS DAILY TRADE SETUPS\n\nNo high-confidence live setup met the configured threshold. No trade signal published."
    body += "\n\n" + _format_candidates("🔥 TRENDING WATCHLIST", trending)
    body += "\n\n" + _format_candidates("💎 SMALL-CAP DISCOVERY", small_caps)
    body += "\n\n" + _format_validated_gems([x for x in validated if x.status == "WATCH"][:int(os.getenv("GEM_VALIDATED_OUTPUT_LIMIT","5"))])
    for i in range(0,len(body),4000): await context.bot.send_message(chat_id=CHAT_ID,text=body[i:i+4000])
