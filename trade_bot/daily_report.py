import os
from .live_setup import crypto_setup, stock_setup
from .formatter import format_signal

CRYPTO=[x.strip().upper() for x in os.getenv('WATCHLIST_CRYPTO','BTCUSDT,ETHUSDT,SOLUSDT').split(',') if x.strip()]
STOCKS=[x.strip().upper() for x in os.getenv('WATCHLIST_STOCKS','NVDA,TSLA,AAPL,MSFT,AMZN').split(',') if x.strip()]

def generate_daily_report():
    results=[]
    for symbol in CRYPTO:
        try: results.append(crypto_setup(symbol))
        except Exception as e: results.append(f'⚠️ {symbol}: unavailable — {e}')
    for symbol in STOCKS:
        try: results.append(stock_setup(symbol))
        except Exception as e: results.append(f'⚠️ {symbol}: unavailable — {e}')
    return '📅 AUREILS DAILY TRADE SETUPS\n\n'+'\n\n'.join(format_signal(x) if not isinstance(x,str) else x for x in results)
