import os
from telegram.ext import ContextTypes
from .live_setup import crypto_setup, stock_setup
from .formatter import format_signal
from .journal import record_setup

CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

async def daily_scan(context: ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID:
        return
    symbols=[x.strip().upper() for x in os.getenv('WATCHLIST_CRYPTO','BTCUSDT,ETHUSDT,SOLUSDT').split(',') if x.strip()]
    stocks=[x.strip().upper() for x in os.getenv('WATCHLIST_STOCKS','NVDA,TSLA,AAPL,MSFT,AMZN').split(',') if x.strip()]
    signals=[]
    for symbol in symbols:
        try: signals.append(crypto_setup(symbol))
        except Exception: pass
    for symbol in stocks:
        try: signals.append(stock_setup(symbol))
        except Exception: pass
    threshold=int(os.getenv('MIN_SIGNAL_SCORE','70'))
    publish=[s for s in signals if s.direction != 'WAIT' and s.score >= threshold]
    for s in publish: record_setup(s)
    if not publish:
        await context.bot.send_message(chat_id=CHAT_ID,text='📊 AUREILS DAILY TRADE SETUPS\n\nNo high-confidence setup met the configured threshold. No trade signal published.')
        return
    body='📊 AUREILS DAILY TRADE SETUPS\n\n'+'\n\n'.join(format_signal(s) for s in publish)
    await context.bot.send_message(chat_id=CHAT_ID,text=body[:4096])
