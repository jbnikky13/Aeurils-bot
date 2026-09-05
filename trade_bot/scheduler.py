import os
from telegram.ext import ContextTypes
from .live_setup import crypto_setup, stock_setup
from .formatter import format_signal
from .journal import record_setup

CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


async def _run_crypto(symbol):
    try:
        return await crypto_setup(symbol)
    except Exception:
        return None


def _run_stock(symbol):
    try:
        return stock_setup(symbol)
    except Exception:
        return None


async def daily_scan(context: ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID is not configured")

    symbols = [x.strip().upper() for x in os.getenv("WATCHLIST_CRYPTO", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if x.strip()]
    stocks = [x.strip().upper() for x in os.getenv("WATCHLIST_STOCKS", "NVDA,TSLA,AAPL,MSFT,AMZN").split(",") if x.strip()]

    crypto_results = await __import__("asyncio").gather(*[_run_crypto(s) for s in symbols])
    stock_results = [_run_stock(s) for s in stocks]
    signals = [s for s in [*crypto_results, *stock_results] if s is not None]

    threshold = int(os.getenv("MIN_SIGNAL_SCORE", "70"))
    publish = [s for s in signals if s.direction != "WAIT" and s.score >= threshold]
    for signal in publish:
        record_setup(signal)

    if not publish:
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text="📊 AUREILS DAILY TRADE SETUPS\n\nNo high-confidence live setup met the configured threshold. No trade signal published."
        )
        return

    body = "📊 AUREILS DAILY TRADE SETUPS\n\n" + "\n\n".join(format_signal(s) for s in publish)
    for i in range(0, len(body), 4000):
        await context.bot.send_message(chat_id=CHAT_ID, text=body[i:i + 4000])
