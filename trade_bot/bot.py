import os
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from .formatter import format_signal
from .live_setup import crypto_setup, stock_setup

CRYPTO = [x.strip() for x in os.getenv("WATCHLIST_CRYPTO", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if x.strip()]
STOCKS = [x.strip() for x in os.getenv("WATCHLIST_STOCKS", "NVDA,TSLA,AAPL,MSFT,AMZN").split(",") if x.strip()]


def safe_setup(symbol: str, asset_type: str):
    try:
        return crypto_setup(symbol) if asset_type == "crypto" else stock_setup(symbol)
    except Exception as exc:
        return f"⚠️ {symbol}: live analysis unavailable — {exc}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Aeurils Trade Bot\n\n/today — daily market scan\n/crypto — crypto setups\n/stocks — stock setups\n/setup BTCUSDT — one asset\n/help — commands\n\nSignals are research only; verify live prices and manage risk.")


async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setup BTCUSDT")
        return
    symbol = context.args[0].upper()
    asset_type = "crypto" if symbol.endswith("USDT") else "stock"
    result = safe_setup(symbol, asset_type)
    await update.message.reply_text(format_signal(result) if not isinstance(result, str) else result)


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    results = [safe_setup(s, "crypto") for s in CRYPTO] + [safe_setup(s, "stock") for s in STOCKS]
    text = "📅 DAILY MARKET SCAN\n" + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") + "\n\n" + "\n\n".join(format_signal(x) if not isinstance(x, str) else x for x in results)
    await update.message.reply_text(text[:3900])


async def crypto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    results = [safe_setup(s, "crypto") for s in CRYPTO]
    await update.message.reply_text("\n\n".join(format_signal(x) if not isinstance(x, str) else x for x in results)[:3900])


async def stocks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    results = [safe_setup(s, "stock") for s in STOCKS]
    await update.message.reply_text("\n\n".join(format_signal(x) if not isinstance(x, str) else x for x in results)[:3900])


async def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()
    for name, handler in [("start", start), ("today", today), ("crypto", crypto), ("stocks", stocks), ("setup", setup)]:
        app.add_handler(CommandHandler(name, handler))
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
