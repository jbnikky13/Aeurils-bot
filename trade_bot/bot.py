import os
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from .formatter import format_signal
from .live_setup import crypto_setup, stock_setup
from .journal import performance
from .scheduler import daily_scan
from .gem_finder import discover_gems, discover_small_caps
from .gem_score import scan_candidates
from .signal_lifecycle import record_open

CRYPTO=[x.strip() for x in os.getenv("WATCHLIST_CRYPTO","BTCUSDT,ETHUSDT,SOLUSDT").split(",") if x.strip()]
STOCKS=[x.strip() for x in os.getenv("WATCHLIST_STOCKS","NVDA,TSLA,AAPL,MSFT,AMZN").split(",") if x.strip()]

def _fmt_discovery(title, items):
    lines=[title]
    for i,x in enumerate(items,1):
        lines.append(f"{i}. {x['name']} ({x['symbol'].upper()}) — score {x['score']}/100 | MCap ${x['market_cap']:,.0f} | Vol ${x['volume_24h']:,.0f}")
    return "\n".join(lines) if items else title+"\nNo qualifying candidates found."

def _fmt_gems(items):
    if not items: return "💎 AURELIS GEM VALIDATION\nNo candidates passed discovery filters."
    lines=["💎 AURELIS GEM VALIDATION"]
    for i,x in enumerate(items,1):
        reasons="; ".join(x.reasons[:3])
        lines.append(f"{i}. {x.name} ({x.symbol}) — {x.status} | Gem {x.final_score:.1f}/100 | {reasons}")
    lines.append("\nWATCH means research/watchlist status, not an automatic buy signal.")
    return "\n".join(lines)

async def safe_setup(symbol, asset_type):
    try: return await crypto_setup(symbol) if asset_type=="crypto" else stock_setup(symbol)
    except Exception as exc: return f"⚠️ {symbol}: live analysis unavailable — {exc}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Aeurils Trade Bot\n\n/today — daily market scan\n/crypto — crypto setups\n/stocks — stock setups\n/trending — trending crypto\n/gems — validated small-cap candidates\n/setup BTCUSDT — one asset\n/performance — journal\n/help — commands\n\nOnly signals that pass the complete quality gate are actionable. Everything else is WATCH/WAIT. Research only; manage risk.")

async def help_command(update, context): await start(update,context)
async def setup(update, context):
    if not context.args: return await update.message.reply_text("Usage: /setup BTCUSDT")
    symbol=context.args[0].upper(); result=await safe_setup(symbol,"crypto" if symbol.endswith("USDT") else "stock")
    if isinstance(result,str): return await update.message.reply_text(result+"\n\nStatus: WATCH/WAIT — not actionable.")
    threshold=int(os.getenv("MIN_SIGNAL_SCORE","70"))
    if result.direction == "WAIT" or result.score < threshold:
        return await update.message.reply_text(format_signal(result)+"\n\nStatus: WATCH/WAIT — quality gate not passed. No trade published.")
    sid,created=record_open(result)
    await update.message.reply_text(format_signal(result)+f"\nSignal ID: {sid}\nStatus: {'OPEN' if created else 'DUPLICATE — suppressed'}")
async def today(update, context):
    results=[await safe_setup(s,"crypto") for s in CRYPTO]+[await safe_setup(s,"stock") for s in STOCKS]
    text="📅 DAILY MARKET SCAN\n"+datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")+"\n\n"+"\n\n".join(format_signal(x) if not isinstance(x,str) else x for x in results)
    await update.message.reply_text(text[:3900])
async def crypto(update, context):
    results=[await safe_setup(s,"crypto") for s in CRYPTO]; await update.message.reply_text("\n\n".join(format_signal(x) if not isinstance(x,str) else x for x in results)[:3900])
async def stocks(update, context):
    results=[await safe_setup(s,"stock") for s in STOCKS]; await update.message.reply_text("\n\n".join(format_signal(x) if not isinstance(x,str) else x for x in results)[:3900])
async def trending(update, context):
    try: await update.message.reply_text(_fmt_discovery("🔥 TRENDING CRYPTO",discover_gems(10)))
    except Exception as exc: await update.message.reply_text(f"⚠️ Trending scan unavailable: {exc}")
async def gems(update, context):
    try:
        items=await scan_candidates(limit=int(os.getenv("GEM_VALIDATION_LIMIT","5")))
        await update.message.reply_text(_fmt_gems(items)[:3900])
    except Exception as exc: await update.message.reply_text(f"⚠️ Gem validation unavailable: {exc}")
async def perf(update, context):
    stats=performance(); await update.message.reply_text("📈 AURELIS PERFORMANCE\n\n"+"\n".join(f"{k}: {v}" for k,v in stats.items()))

async def main():
    app=Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    for name,handler in [("start",start),("help",help_command),("today",today),("crypto",crypto),("stocks",stocks),("trending",trending),("gems",gems),("setup",setup),("performance",perf)]: app.add_handler(CommandHandler(name,handler))
    if app.job_queue:
        from datetime import time
        app.job_queue.run_daily(daily_scan,time(hour=int(os.getenv("DAILY_SCAN_HOUR_UTC","08")),minute=int(os.getenv("DAILY_SCAN_MINUTE_UTC","00")),tzinfo=timezone.utc),name="daily-market-scan")
    app.run_polling()
if __name__=="__main__":
    import asyncio; asyncio.run(main())
