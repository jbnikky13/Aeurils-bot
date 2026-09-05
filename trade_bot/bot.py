import os
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from .formatter import format_signal
from .signal_engine import build_setup

CRYPTO = [x for x in os.getenv("WATCHLIST_CRYPTO", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if x]
STOCKS = [x for x in os.getenv("WATCHLIST_STOCKS", "NVDA,TSLA,AAPL,MSFT,AMZN").split(",") if x]


def demo_setup(symbol: str, asset_type: str):
    return build_setup(symbol, asset_type, 100.0, 50, 50, 50, 0.0, 0.0, 2.0)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Aeurils Trade Bot\n\n/today — daily watchlist\n/crypto — crypto setups\n/stocks — stock setups\n/setup BTCUSDT — one asset\n/help — commands\n\nResearch only; verify live data and manage risk.")


async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setup BTCUSDT")
        return
    symbol = context.args[0].upper()
    asset_type = "crypto" if symbol.endswith("USDT") else "stock"
    await update.message.reply_text(format_signal(demo_setup(symbol, asset_type)))


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📅 DAILY MARKET SCAN\n" + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") + "\n\n" + "\n\n".join(format_signal(demo_setup(s, "crypto")) for s in CRYPTO[:3]))


async def crypto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\n\n".join(format_signal(demo_setup(s, "crypto")) for s in CRYPTO))


async def stocks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\n\n".join(format_signal(demo_setup(s, "stock")) for s in STOCKS))


async def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()
    for name, handler in [("start", start), ("today", today), ("crypto", crypto), ("stocks", stocks), ("setup", setup)]:
        app.add_handler(CommandHandler(name, handler))
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
